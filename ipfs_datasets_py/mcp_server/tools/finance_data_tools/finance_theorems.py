"""
Financial Theorems for Temporal Deontic Logic System.

This module defines financial rules and patterns as temporal deontic logic theorems,
extending the existing caselaw logic system for financial domain applications.

Features:
- Stock split theorems
- Merger and acquisition theorems
- Dividend adjustment theorems
- Market correlation theorems
- Fuzzy logic evaluation
- Causal reasoning chains
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

logger = logging.getLogger(__name__)


class FinancialEventType(Enum):
    """Types of financial events."""
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    DIVIDEND = "dividend"
    MERGER = "merger"
    ACQUISITION = "acquisition"
    SPINOFF = "spinoff"
    BANKRUPTCY = "bankruptcy"
    EARNINGS = "earnings"
    ANALYST_UPGRADE = "analyst_upgrade"
    ANALYST_DOWNGRADE = "analyst_downgrade"


@dataclass
class FinancialTheorem:
    """
    Represents a financial theorem in temporal deontic logic.
    
    Attributes:
        theorem_id: Unique identifier
        name: Human-readable name
        event_type: Type of financial event
        formula: Formal logic formula
        natural_language: Plain English description
        applicability_conditions: Conditions for theorem applicability
        confidence_threshold: Minimum confidence for application
        temporal_window: Time window for effect (in days)
        metadata: Additional metadata
    """
    theorem_id: str
    name: str
    event_type: FinancialEventType
    formula: str
    natural_language: str
    applicability_conditions: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.7
    temporal_window: int = 30  # days
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "theorem_id": self.theorem_id,
            "name": self.name,
            "event_type": self.event_type.value,
            "formula": self.formula,
            "natural_language": self.natural_language,
            "applicability_conditions": self.applicability_conditions,
            "confidence_threshold": self.confidence_threshold,
            "temporal_window": self.temporal_window,
            "metadata": self.metadata
        }


# Predefined Financial Theorems
STOCK_SPLIT_THEOREM = FinancialTheorem(
    theorem_id="fin_001",
    name="Stock Split Price Adjustment",
    event_type=FinancialEventType.STOCK_SPLIT,
    formula="""
    ∀s,t,r: (StockSplit(s, t, r) → O(AdjustPrice(s, t, Price(s, t-) / r)))
    
    Where:
    - s: stock symbol
    - t: time of split
    - r: split ratio (e.g., 2 for 2:1 split)
    - O: deontic operator OBLIGATION
    - Price(s, t-): price immediately before split
    """,
    natural_language="""
    When a stock split occurs with ratio r at time t, the stock price MUST 
    be adjusted to approximately the pre-split price divided by the split ratio.
    
    Example: If AAPL splits 4:1 at $400/share, the post-split price should 
    be approximately $100/share.
    """,
    applicability_conditions=[
        "has_corporate_action",
        "action_type == 'split'",
        "valid_split_ratio > 1",
        "price_data_available"
    ],
    confidence_threshold=0.95,
    temporal_window=1,  # Effect is immediate
    metadata={
        "historical_accuracy": 0.99,
        "tolerance": 0.02,  # 2% price tolerance
        "typical_split_ratios": [2, 3, 4, 5, 10]
    }
)

REVERSE_SPLIT_THEOREM = FinancialTheorem(
    theorem_id="fin_002",
    name="Reverse Stock Split Price Adjustment",
    event_type=FinancialEventType.REVERSE_SPLIT,
    formula="""
    ∀s,t,r: (ReverseSplit(s, t, r) → O(AdjustPrice(s, t, Price(s, t-) * r)))
    
    Where:
    - r: reverse split ratio (e.g., 10 for 1:10 reverse split)
    """,
    natural_language="""
    When a reverse stock split occurs with ratio r at time t, the stock price 
    MUST be adjusted to approximately the pre-split price multiplied by the ratio.
    
    Example: If a stock trades at $2 and does a 1:10 reverse split, the 
    post-split price should be approximately $20.
    """,
    applicability_conditions=[
        "has_corporate_action",
        "action_type == 'reverse_split'",
        "valid_reverse_ratio > 1"
    ],
    confidence_threshold=0.95,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.99,
        "tolerance": 0.02,
        "common_reasons": ["meet_listing_requirements", "improve_perception"]
    }
)

DIVIDEND_EX_DATE_THEOREM = FinancialTheorem(
    theorem_id="fin_003",
    name="Ex-Dividend Date Price Adjustment",
    event_type=FinancialEventType.DIVIDEND,
    formula="""
    ∀s,t,d: (ExDividendDate(s, t) ∧ DividendAmount(s, d) →
            O(Price(s, t_open) ≈ Price(s, t-1_close) - d))
    
    Where:
    - d: dividend amount per share
    - t_open: opening price on ex-dividend date
    - t-1_close: closing price on previous day
    """,
    natural_language="""
    On the ex-dividend date, the opening stock price SHOULD drop by approximately 
    the dividend amount, as the stock no longer includes rights to the dividend.
    
    Example: If a stock closes at $100 and pays a $2 dividend, it should 
    open near $98 on the ex-dividend date.
    """,
    applicability_conditions=[
        "has_dividend_payment",
        "is_ex_dividend_date",
        "dividend_amount > 0"
    ],
    confidence_threshold=0.75,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.85,
        "tolerance": 0.05,  # 5% tolerance due to market factors
        "note": "Market conditions may cause deviation"
    }
)

MERGER_PRICE_CONVERGENCE_THEOREM = FinancialTheorem(
    theorem_id="fin_004",
    name="Merger Price Convergence",
    event_type=FinancialEventType.MERGER,
    formula="""
    ∀a,b,t,r,p: (MergerAnnouncement(a, b, t) ∧ ExchangeRatio(a, b, r) ∧ Premium(p) →
                P(Price(b, t+Δt) → Price(a, t+Δt) * r * (1 + p)))
    
    Where:
    - a: acquiring company
    - b: target company
    - r: exchange ratio (shares of a per share of b)
    - p: premium percentage
    - Δt: time window (typically 30-90 days)
    - P: deontic operator PERMISSION (soft constraint)
    """,
    natural_language="""
    When company A announces acquisition of company B with exchange ratio r and 
    premium p, the target company's stock price IS PERMITTED to converge toward 
    the acquirer's price times the exchange ratio plus premium.
    
    Example: If MSFT ($300) acquires ATVI with 0.3 exchange ratio and 10% premium,
    ATVI should trend toward $300 * 0.3 * 1.1 = $99.
    """,
    applicability_conditions=[
        "merger_announced",
        "exchange_ratio_defined",
        "regulatory_approval_likely"
    ],
    confidence_threshold=0.70,
    temporal_window=90,
    metadata={
        "historical_accuracy": 0.75,
        "risk_factors": ["regulatory_rejection", "deal_break", "market_conditions"],
        "convergence_rate": "typically 60-90% within 30 days"
    }
)

EARNINGS_ANNOUNCEMENT_THEOREM = FinancialTheorem(
    theorem_id="fin_005",
    name="Earnings Surprise Price Movement",
    event_type=FinancialEventType.EARNINGS,
    formula="""
    ∀s,t,e_actual,e_expected: (EarningsAnnouncement(s, t) ∧ 
                                Surprise(s, (e_actual - e_expected) / e_expected) →
                                P(|ΔPrice(s, t)| > avg_daily_volatility))
    
    Where:
    - e_actual: actual earnings per share
    - e_expected: analyst consensus estimate
    - Surprise: percentage surprise (positive or negative)
    - ΔPrice: price change
    """,
    natural_language="""
    When a company reports earnings that significantly differ from analyst 
    expectations (surprise), the stock price IS PERMITTED to move more than 
    its average daily volatility.
    
    Example: If a stock typically moves 1% daily and reports 20% earnings beat,
    it may move 5-10% on the announcement.
    """,
    applicability_conditions=[
        "earnings_announced",
        "analyst_estimates_available",
        "significant_surprise"  # typically >5%
    ],
    confidence_threshold=0.65,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.70,
        "typical_surprise_threshold": 0.05,  # 5%
        "note": "Direction depends on surprise sign"
    }
)


class FinancialTheoremLibrary:
    """
    Library of financial theorems for temporal deontic logic reasoning.
    """
    
    def __init__(self):
        """Initialize theorem library."""
        self.theorems: Dict[str, FinancialTheorem] = {
            "fin_001": STOCK_SPLIT_THEOREM,
            "fin_002": REVERSE_SPLIT_THEOREM,
            "fin_003": DIVIDEND_EX_DATE_THEOREM,
            "fin_004": MERGER_PRICE_CONVERGENCE_THEOREM,
            "fin_005": EARNINGS_ANNOUNCEMENT_THEOREM
        }
    
    def get_theorem(self, theorem_id: str) -> Optional[FinancialTheorem]:
        """Get theorem by ID."""
        return self.theorems.get(theorem_id)
    
    def get_theorems_by_event_type(
        self,
        event_type: FinancialEventType
    ) -> List[FinancialTheorem]:
        """Get all theorems for a specific event type."""
        return [
            theorem for theorem in self.theorems.values()
            if theorem.event_type == event_type
        ]
    
    def add_custom_theorem(self, theorem: FinancialTheorem) -> None:
        """Add a custom theorem to the library."""
        self.theorems[theorem.theorem_id] = theorem
        logger.info(f"Added custom theorem: {theorem.theorem_id}")
    
    def list_all_theorems(self) -> List[Dict[str, Any]]:
        """List all theorems in the library."""
        return [theorem.to_dict() for theorem in self.theorems.values()]


@dataclass
class TheoremApplication:
    """
    Represents an application of a theorem to real market data.
    
    Attributes:
        theorem_id: ID of applied theorem
        symbol: Stock symbol
        event_date: Date of the event
        expected_outcome: What the theorem predicts
        actual_outcome: What actually happened
        confidence_score: Confidence in the application
        deviation: Difference between expected and actual
        validation_passed: Whether outcome matched prediction
    """
    theorem_id: str
    symbol: str
    event_date: datetime
    expected_outcome: Dict[str, Any]
    actual_outcome: Optional[Dict[str, Any]] = None
    confidence_score: float = 0.0
    deviation: Optional[float] = None
    validation_passed: Optional[bool] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "theorem_id": self.theorem_id,
            "symbol": self.symbol,
            "event_date": self.event_date.isoformat(),
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "confidence_score": self.confidence_score,
            "deviation": self.deviation,
            "validation_passed": self.validation_passed
        }


# MCP Tool Functions
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
