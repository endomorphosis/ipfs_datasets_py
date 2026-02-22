"""Financial Theorems engine — canonical business-logic location.

Contains domain classes (``FinancialEventType``, ``FinancialTheorem``,
``FinancialTheoremLibrary``, ``TheoremApplication``) and five pre-defined
stock/merger/dividend theorems for temporal deontic logic reasoning.

These were previously embedded inside the MCP tool wrapper at
``ipfs_datasets_py/mcp_server/tools/finance_data_tools/finance_theorems.py``.

Keeping them here means the same logic can be used from:
- ``ipfs_datasets_py.processors.finance.finance_theorems_engine`` (package import)
- ``ipfs_datasets_py-cli finance theorems ...``                     (CLI)
- The MCP server tool (thin wrapper in tools/finance_data_tools/)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain enumerations
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Domain data-classes
# ---------------------------------------------------------------------------

@dataclass
class FinancialTheorem:
    """Represents a financial theorem in temporal deontic logic.

    Attributes:
        theorem_id: Unique identifier.
        name: Human-readable name.
        event_type: Type of financial event.
        formula: Formal logic formula.
        natural_language: Plain English description.
        applicability_conditions: Conditions for theorem applicability.
        confidence_threshold: Minimum confidence for application.
        temporal_window: Time window for effect (in days).
        metadata: Additional metadata.
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
        """Convert to dictionary for JSON serialisation."""
        return {
            "theorem_id": self.theorem_id,
            "name": self.name,
            "event_type": self.event_type.value,
            "formula": self.formula,
            "natural_language": self.natural_language,
            "applicability_conditions": self.applicability_conditions,
            "confidence_threshold": self.confidence_threshold,
            "temporal_window": self.temporal_window,
            "metadata": self.metadata,
        }


@dataclass
class TheoremApplication:
    """Represents an application of a theorem to real market data.

    Attributes:
        theorem_id: ID of applied theorem.
        symbol: Stock symbol.
        event_date: Date of the event.
        expected_outcome: What the theorem predicts.
        actual_outcome: What actually happened.
        confidence_score: Confidence in the application.
        deviation: Difference between expected and actual.
        validation_passed: Whether outcome matched prediction.
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
            "validation_passed": self.validation_passed,
        }


# ---------------------------------------------------------------------------
# Pre-defined theorems
# ---------------------------------------------------------------------------

STOCK_SPLIT_THEOREM = FinancialTheorem(
    theorem_id="fin_001",
    name="Stock Split Price Adjustment",
    event_type=FinancialEventType.STOCK_SPLIT,
    formula=(
        "∀s,t,r: (StockSplit(s, t, r) → O(AdjustPrice(s, t, Price(s, t-) / r)))\n\n"
        "Where:\n"
        "- s: stock symbol\n"
        "- t: time of split\n"
        "- r: split ratio (e.g. 2 for 2:1 split)\n"
        "- O: deontic operator OBLIGATION\n"
        "- Price(s, t-): price immediately before split"
    ),
    natural_language=(
        "When a stock split occurs with ratio r at time t, the stock price MUST be adjusted "
        "to approximately the pre-split price divided by the split ratio.\n\n"
        "Example: If AAPL splits 4:1 at $400/share, the post-split price should be "
        "approximately $100/share."
    ),
    applicability_conditions=[
        "has_corporate_action",
        "action_type == 'split'",
        "valid_split_ratio > 1",
        "price_data_available",
    ],
    confidence_threshold=0.95,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.99,
        "tolerance": 0.02,
        "typical_split_ratios": [2, 3, 4, 5, 10],
    },
)

REVERSE_SPLIT_THEOREM = FinancialTheorem(
    theorem_id="fin_002",
    name="Reverse Stock Split Price Adjustment",
    event_type=FinancialEventType.REVERSE_SPLIT,
    formula=(
        "∀s,t,r: (ReverseSplit(s, t, r) → O(AdjustPrice(s, t, Price(s, t-) * r)))\n\n"
        "Where:\n"
        "- r: reverse split ratio (e.g. 10 for 1:10 reverse split)"
    ),
    natural_language=(
        "When a reverse stock split occurs with ratio r at time t, the stock price MUST be "
        "adjusted to approximately the pre-split price multiplied by the ratio.\n\n"
        "Example: If a stock trades at $2 and does a 1:10 reverse split, the post-split "
        "price should be approximately $20."
    ),
    applicability_conditions=[
        "has_corporate_action",
        "action_type == 'reverse_split'",
        "valid_reverse_ratio > 1",
    ],
    confidence_threshold=0.95,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.99,
        "tolerance": 0.02,
        "common_reasons": ["meet_listing_requirements", "improve_perception"],
    },
)

DIVIDEND_EX_DATE_THEOREM = FinancialTheorem(
    theorem_id="fin_003",
    name="Ex-Dividend Date Price Adjustment",
    event_type=FinancialEventType.DIVIDEND,
    formula=(
        "∀s,t,d: (ExDividendDate(s, t) ∧ DividendAmount(s, d) →\n"
        "        O(Price(s, t_open) ≈ Price(s, t-1_close) - d))\n\n"
        "Where:\n"
        "- d: dividend amount per share\n"
        "- t_open: opening price on ex-dividend date\n"
        "- t-1_close: closing price on previous day"
    ),
    natural_language=(
        "On the ex-dividend date, the opening stock price SHOULD drop by approximately "
        "the dividend amount, as the stock no longer includes rights to the dividend.\n\n"
        "Example: If a stock closes at $100 and pays a $2 dividend, it should open near "
        "$98 on the ex-dividend date."
    ),
    applicability_conditions=[
        "has_dividend_payment",
        "is_ex_dividend_date",
        "dividend_amount > 0",
    ],
    confidence_threshold=0.75,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.85,
        "tolerance": 0.05,
        "note": "Market conditions may cause deviation",
    },
)

MERGER_PRICE_CONVERGENCE_THEOREM = FinancialTheorem(
    theorem_id="fin_004",
    name="Merger Price Convergence",
    event_type=FinancialEventType.MERGER,
    formula=(
        "∀a,b,t,r,p: (MergerAnnouncement(a, b, t) ∧ ExchangeRatio(a, b, r) ∧ Premium(p) →\n"
        "            P(Price(b, t+Δt) → Price(a, t+Δt) * r * (1 + p)))\n\n"
        "Where:\n"
        "- a: acquiring company\n"
        "- b: target company\n"
        "- r: exchange ratio (shares of a per share of b)\n"
        "- p: premium percentage\n"
        "- Δt: time window (typically 30-90 days)\n"
        "- P: deontic operator PERMISSION (soft constraint)"
    ),
    natural_language=(
        "When company A announces acquisition of company B with exchange ratio r and premium p, "
        "the target company's stock price IS PERMITTED to converge toward the acquirer's price "
        "times the exchange ratio plus premium.\n\n"
        "Example: If MSFT ($300) acquires ATVI with 0.3 exchange ratio and 10% premium, ATVI "
        "should trend toward $300 * 0.3 * 1.1 = $99."
    ),
    applicability_conditions=[
        "merger_announced",
        "exchange_ratio_defined",
        "regulatory_approval_likely",
    ],
    confidence_threshold=0.70,
    temporal_window=90,
    metadata={
        "historical_accuracy": 0.75,
        "risk_factors": ["regulatory_rejection", "deal_break", "market_conditions"],
        "convergence_rate": "typically 60-90% within 30 days",
    },
)

EARNINGS_ANNOUNCEMENT_THEOREM = FinancialTheorem(
    theorem_id="fin_005",
    name="Earnings Surprise Price Movement",
    event_type=FinancialEventType.EARNINGS,
    formula=(
        "∀s,t,e_actual,e_expected: (EarningsAnnouncement(s, t) ∧\n"
        "                            Surprise(s, (e_actual - e_expected) / e_expected) →\n"
        "                            P(|ΔPrice(s, t)| > avg_daily_volatility))\n\n"
        "Where:\n"
        "- e_actual: actual earnings per share\n"
        "- e_expected: analyst consensus estimate\n"
        "- Surprise: percentage surprise (positive or negative)\n"
        "- ΔPrice: price change"
    ),
    natural_language=(
        "When a company reports earnings that significantly differ from analyst expectations "
        "(surprise), the stock price IS PERMITTED to move more than its average daily "
        "volatility.\n\n"
        "Example: If a stock typically moves 1% daily and reports a 20% earnings beat, it "
        "may move 5-10% on the announcement."
    ),
    applicability_conditions=[
        "earnings_announced",
        "analyst_estimates_available",
        "significant_surprise",  # typically >5 %
    ],
    confidence_threshold=0.65,
    temporal_window=1,
    metadata={
        "historical_accuracy": 0.70,
        "typical_surprise_threshold": 0.05,
        "note": "Direction depends on surprise sign",
    },
)


# ---------------------------------------------------------------------------
# Theorem library / registry
# ---------------------------------------------------------------------------

class FinancialTheoremLibrary:
    """Library of financial theorems for temporal deontic logic reasoning."""

    def __init__(self) -> None:
        """Initialise with the five pre-defined theorems."""
        self.theorems: Dict[str, FinancialTheorem] = {
            "fin_001": STOCK_SPLIT_THEOREM,
            "fin_002": REVERSE_SPLIT_THEOREM,
            "fin_003": DIVIDEND_EX_DATE_THEOREM,
            "fin_004": MERGER_PRICE_CONVERGENCE_THEOREM,
            "fin_005": EARNINGS_ANNOUNCEMENT_THEOREM,
        }

    def get_theorem(self, theorem_id: str) -> Optional[FinancialTheorem]:
        """Return a theorem by ID, or ``None`` if not found."""
        return self.theorems.get(theorem_id)

    def get_theorems_by_event_type(
        self, event_type: FinancialEventType
    ) -> List[FinancialTheorem]:
        """Return all theorems for a specific event type."""
        return [t for t in self.theorems.values() if t.event_type == event_type]

    def add_custom_theorem(self, theorem: FinancialTheorem) -> None:
        """Add a custom theorem to the library."""
        self.theorems[theorem.theorem_id] = theorem
        logger.info("Added custom theorem: %s", theorem.theorem_id)

    def list_all_theorems(self) -> List[Dict[str, Any]]:
        """Return a serialisable list of all theorems."""
        return [t.to_dict() for t in self.theorems.values()]


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
]
