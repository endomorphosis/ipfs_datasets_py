"""
Stock Market Data Scraper Engine.

Business logic classes for stock data scraping, separated from MCP tool wrappers.
Provides dataclass models and scraper base classes with rate limiting and retry logic.

MCP tool functions that wrap these classes live in stock_scrapers.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StockDataPoint:
    """
    Represents a single stock data point (OHLCV).

    Attributes:
        symbol: Stock ticker symbol (e.g., 'AAPL')
        timestamp: Data point timestamp
        open: Opening price
        high: Highest price
        low: Lowest price
        close: Closing price
        volume: Trading volume
        adjusted_close: Adjusted closing price (after splits/dividends)
        metadata: Additional metadata (splits, dividends, etc.)
    """

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate the data point for consistency.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check OHLC consistency
        if self.high < self.low:
            errors.append(f"High ({self.high}) is less than Low ({self.low})")

        if self.open > self.high or self.open < self.low:
            errors.append(f"Open ({self.open}) is outside High-Low range")

        if self.close > self.high or self.close < self.low:
            errors.append(f"Close ({self.close}) is outside High-Low range")

        # Check for negative values
        if any(v < 0 for v in [self.open, self.high, self.low, self.close]):
            errors.append("Negative price values detected")

        if self.volume < 0:
            errors.append(f"Negative volume: {self.volume}")

        # Check for zero prices (usually indicates missing data)
        if any(v == 0 for v in [self.open, self.high, self.low, self.close]):
            errors.append("Zero price values detected (possible missing data)")

        return len(errors) == 0, errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "adjusted_close": self.adjusted_close,
            "metadata": self.metadata,
        }


@dataclass
class CorporateAction:
    """
    Represents a corporate action (split, dividend, etc.).

    Attributes:
        symbol: Stock ticker symbol
        action_type: Type of action ('split', 'dividend', 'merger', etc.)
        date: Action date
        details: Action-specific details
    """

    symbol: str
    action_type: str  # 'split', 'dividend', 'merger', 'acquisition'
    date: datetime
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "symbol": self.symbol,
            "action_type": self.action_type,
            "date": self.date.isoformat(),
            "details": self.details,
        }


class StockDataScraper:
    """
    Base class for stock data scrapers.

    Provides common functionality for all stock data sources including
    rate limiting, error handling, and data validation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_calls: int = 5,
        rate_limit_period: int = 60,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        """
        Initialize the scraper.

        Args:
            api_key: API key for the data source (if required)
            rate_limit_calls: Maximum number of API calls per period
            rate_limit_period: Rate limit period in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.api_key = api_key
        self.rate_limit_calls = rate_limit_calls
        self.rate_limit_period = rate_limit_period
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Rate limiting state
        self._call_times: List[float] = []
        self._last_call_time = 0.0

    def _check_rate_limit(self) -> None:
        """
        Check and enforce rate limiting.

        Blocks until it's safe to make another API call.
        """
        now = time.time()

        # Remove calls outside the rate limit period
        self._call_times = [t for t in self._call_times if now - t < self.rate_limit_period]

        # If we've hit the rate limit, wait
        if len(self._call_times) >= self.rate_limit_calls:
            oldest_call = self._call_times[0]
            wait_time = self.rate_limit_period - (now - oldest_call)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)

        # Record this call
        self._call_times.append(time.time())

    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """
        Execute function with exponential backoff retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Function result

        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries} attempts failed")

        raise last_exception

    def fetch_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[StockDataPoint]:
        """
        Fetch stock data for a symbol within a date range.

        This is a template method to be implemented by subclasses.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date for data
            end_date: End date for data
            interval: Data interval ('1d', '1h', '5m', etc.)

        Returns:
            List of StockDataPoint objects

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement fetch_data")

    def fetch_corporate_actions(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[CorporateAction]:
        """
        Fetch corporate actions for a symbol within a date range.

        This is a template method to be implemented by subclasses.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date
            end_date: End date

        Returns:
            List of CorporateAction objects

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement fetch_corporate_actions")

    def validate_data(
        self,
        data_points: List[StockDataPoint],
    ) -> Tuple[List[StockDataPoint], List[Dict[str, Any]]]:
        """
        Validate a list of data points.

        Args:
            data_points: List of data points to validate

        Returns:
            Tuple of (valid_data_points, validation_errors)
        """
        valid_points = []
        errors = []

        for point in data_points:
            is_valid, point_errors = point.validate()
            if is_valid:
                valid_points.append(point)
            else:
                errors.append(
                    {
                        "symbol": point.symbol,
                        "timestamp": point.timestamp.isoformat(),
                        "errors": point_errors,
                    }
                )

        if errors:
            logger.warning(f"Found {len(errors)} invalid data points")

        return valid_points, errors


class YahooFinanceScraper(StockDataScraper):
    """
    Stock data scraper using Yahoo Finance as the data source.

    This is a placeholder implementation. In production, you would use
    libraries like yfinance or implement custom API calls.
    """

    def __init__(self, **kwargs):
        """Initialize Yahoo Finance scraper."""
        super().__init__(**kwargs)
        self.source = "yahoo_finance"

    def fetch_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[StockDataPoint]:
        """
        Fetch stock data from Yahoo Finance.

        Note: This is a placeholder. In production, integrate with yfinance library
        or Yahoo Finance API.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date for data
            end_date: End date for data
            interval: Data interval

        Returns:
            List of StockDataPoint objects
        """
        self._check_rate_limit()

        logger.info(
            f"Fetching {symbol} data from {start_date.date()} to {end_date.date()} "
            f"with {interval} interval"
        )

        # Placeholder: In production, make actual API call
        # Example with yfinance:
        # import yfinance as yf
        # ticker = yf.Ticker(symbol)
        # df = ticker.history(start=start_date, end=end_date, interval=interval)
        # return self._convert_dataframe_to_datapoints(df, symbol)

        logger.warning(
            "YahooFinanceScraper.fetch_data is a placeholder. "
            "Install yfinance and implement actual data fetching."
        )
        return []

    def fetch_corporate_actions(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[CorporateAction]:
        """
        Fetch corporate actions from Yahoo Finance.

        Note: This is a placeholder implementation.

        Args:
            symbol: Stock ticker symbol
            start_date: Start date
            end_date: End date

        Returns:
            List of CorporateAction objects
        """
        self._check_rate_limit()

        logger.info(f"Fetching corporate actions for {symbol}")

        # Placeholder: In production, fetch from API
        # Example with yfinance:
        # import yfinance as yf
        # ticker = yf.Ticker(symbol)
        # splits = ticker.splits
        # dividends = ticker.dividends
        # return self._convert_to_corporate_actions(splits, dividends, symbol)

        logger.warning(
            "YahooFinanceScraper.fetch_corporate_actions is a placeholder. "
            "Implement actual data fetching."
        )
        return []


__all__ = [
    "StockDataPoint",
    "CorporateAction",
    "StockDataScraper",
    "YahooFinanceScraper",
]
