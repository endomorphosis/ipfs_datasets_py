"""
Tests for lizardpersons_function_tools/llm_context_tools/get_current_time.py.

Tests cover:
- get_current_time default ISO format
- human / timestamp / custom strftime formats
- check_if_within_working_hours mode
- deadline_date mode
- time_between single and dual timestamp modes
"""
import re
import time as time_mod

import pytest

from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.llm_context_tools.get_current_time import (
    get_current_time,
)


class TestGetCurrentTimeFormats:
    """Tests for the default ISO / human / timestamp output formats."""

    def test_returns_str(self):
        """GIVEN no args THEN returns a string."""
        result = get_current_time()
        assert isinstance(result, str)

    def test_iso_format_is_parseable(self):
        """GIVEN format_type='iso' THEN the result parses as an ISO datetime."""
        from datetime import datetime

        result = get_current_time(format_type="iso")
        dt = datetime.fromisoformat(result)
        assert dt is not None

    def test_human_format_matches_pattern(self):
        """GIVEN format_type='human' THEN result matches 'YYYY-MM-DD HH:MM:SS'."""
        result = get_current_time(format_type="human")
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)

    def test_timestamp_format_is_digit_string(self):
        """GIVEN format_type='timestamp' THEN result is a string of digits."""
        result = get_current_time(format_type="timestamp")
        assert result.isdigit()
        # Sanity-check: unix timestamp is > 1_700_000_000
        assert int(result) > 1_700_000_000

    def test_custom_strftime_format(self):
        """GIVEN a custom strftime format THEN it is applied correctly."""
        result = get_current_time(format_type="%Y")
        assert result.isdigit()
        assert len(result) == 4  # four-digit year


class TestGetCurrentTimeSpecialModes:
    """Tests for the special-mode flags (working hours, deadline, time_between)."""

    def test_check_working_hours_returns_bool_str(self):
        """GIVEN check_if_within_working_hours=True THEN returns 'True' or 'False'."""
        result = get_current_time(check_if_within_working_hours=True)
        assert result in ("True", "False")

    def test_deadline_future_returns_str(self):
        """GIVEN a future deadline_date THEN returns a duration string."""
        future_ts = time_mod.time() + 3600  # 1 hour from now
        result = get_current_time(deadline_date=future_ts)
        assert isinstance(result, str)

    def test_deadline_past_returns_deadline_passed_str(self):
        """GIVEN a past deadline_date THEN returns a 'passed' message."""
        past_ts = time_mod.time() - 3600  # 1 hour ago
        result = get_current_time(deadline_date=past_ts)
        assert isinstance(result, str)
        assert "passed" in result.lower()

    def test_time_between_single_timestamp_returns_ago_str(self):
        """GIVEN time_between=(past_ts,) THEN returns 'X ... ago' or similar."""
        past_ts = time_mod.time() - 120  # 2 minutes ago
        result = get_current_time(time_between=(past_ts,))
        assert isinstance(result, str)
        # Should mention 'ago' or a time unit
        assert "ago" in result or any(u in result for u in ("second", "minute", "hour"))

    def test_time_between_two_timestamps_returns_str(self):
        """GIVEN time_between=(t1, t2) THEN returns a duration string."""
        now = time_mod.time()
        result = get_current_time(time_between=(now - 3600, now))
        assert isinstance(result, str)

    def test_time_between_invalid_tuple_raises_value_error(self):
        """GIVEN time_between with 3+ elements THEN raises ValueError."""
        now = time_mod.time()
        with pytest.raises(ValueError):
            get_current_time(time_between=(now, now - 1, now - 2))
