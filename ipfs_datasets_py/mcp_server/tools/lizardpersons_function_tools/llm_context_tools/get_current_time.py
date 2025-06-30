from datetime import datetime, timedelta
from typing import Optional


def _convert_timestamp_to_datetime(timestamp: str | int | float) -> datetime:
    if isinstance(timestamp, str):
        return datetime.fromisoformat(timestamp)
    elif isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(float(timestamp))
    else:
        return timestamp

def _get_days_hours_minutes_seconds(diff: timedelta) -> tuple[int, int, int, int]:
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return days, hours, minutes, seconds


def _get_duration(days: int, hours: int, minutes: int, seconds: int) -> str:
    """
    Format duration into a human-readable string.
    """
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

    return ", ".join(parts) if parts else "Less than a minute"



def _get_time_till_deadline(deadline: str | int | float) -> str:
    """
    Calculate time remaining until a deadline.
    
    Args:
        deadline: Deadline as ISO string, timestamp, or Unix timestamp
        
    Returns:
        str: Human-readable time remaining (e.g., "2 days, 3 hours")
    """
    # Convert deadline to datetime object
    deadline_dt = _convert_timestamp_to_datetime(deadline)

    # Calculate time difference
    now = datetime.now()
    diff = deadline_dt - now

    if diff.total_seconds() <= 0:
        return "Deadline has passed"

    days, hours, minutes, seconds = _get_days_hours_minutes_seconds(diff)

    duration = _get_duration(days, hours, minutes, seconds)
    return duration


def _determine_if_current_time_is_within_working_hours() -> str:
    """
    Determine if the current time is within working hours (9 AM to 5 PM).
    
    Returns:
        str: 'True' if current time is within working hours, 'False' otherwise.
    """
    now = datetime.now()
    return str(now.hour >= 9 and now.hour < 17)


def _duration_since(timestamp: str | int | float) -> str:
    """
    Calculate the duration between a given timestamp and the current time.
    
    Args:
        timestamp: Past timestamp as ISO string, Unix timestamp, or datetime object
        
    Returns:
        str: Human-readable duration since timestamp (e.g., "2 days, 3 hours ago")
    """
    # Convert timestamp to datetime object
    past_dt = _convert_timestamp_to_datetime(timestamp)

    # Calculate time difference
    now = datetime.now()
    diff = now - past_dt
    
    if diff.total_seconds() <= 0:
        return "In the future"
    
    days, hours, minutes, seconds = _get_days_hours_minutes_seconds(diff)

    duration = _get_duration(days, hours, minutes, seconds)
    return f"{duration} ago"

def _time_between(start: str | int | float, end: str | int | float) -> str:
    """
    Get the time difference between two timestamps.
    
    Args:
        start: Start timestamp as ISO string, Unix timestamp, or datetime object
        end: End timestamp as ISO string, Unix timestamp, or datetime object
        
    Returns:
        str: Human-readable duration between timestamps (e.g., "2 days, 3 hours")
    """
    # Convert start and end timestamps to datetime objects
    start_dt = _convert_timestamp_to_datetime(start)
    end_dt = _convert_timestamp_to_datetime(end)

    # Calculate time difference
    diff = end_dt - start_dt
    
    if diff.total_seconds() < 0:
        # If negative, swap and indicate direction
        diff = start_dt - end_dt
        negative = True
    else:
        negative = False
    
    days, hours, minutes, seconds = _get_days_hours_minutes_seconds(diff)
    
    duration = _get_duration(days, hours, minutes, seconds)

    if negative:
        return f"-{duration}"
    return duration


def get_current_time(
        format_type: str = "iso", 
        time_between: Optional[tuple[str | int | float, ...]] = None,
        deadline_date: Optional[str | int | float] = None,
        check_if_within_working_hours: bool = False
        ) -> str:
    """
    Returns the current time in the specified format. Has multiple format options and special modes.
    NOTE These modes are mutually exclusive. If more than one is provided, the first one will be used.

    Args:
        format_type (str): Format type - 'iso', 'human', 'timestamp', or custom strftime format
        time_between (Optional[tuple[str | int | float, str | int | float]]):
            Optional tuple of two timestamps to calculate the time difference between them.
            If provided, the function will return the duration between the two timestamps.
            If a tuple of length 1 is provided, it will calculate the duration between that timestamp and the current time.
        deadline_date (Optional[str | int | float]): 
            Optional deadline date to calculate time remaining.
            If provided, the function will return the time remaining until the deadline instead of the current time.
        check_if_within_working_hours (bool): 
            If True, checks if the local time is within working hours (9 AM to 5 PM). 
            Defaults to False.

    Returns:
        str: Current time in the specified format.
    """
    if isinstance(time_between, tuple):
        if len(time_between) == 1:
            # If only one timestamp is provided, calculate duration since that timestamp
            return _duration_since(time_between[0])
        elif len(time_between) == 2:
            # If two timestamps are provided, calculate time between them
            return _time_between(time_between[0], time_between[1])
        else:
            raise ValueError("time_between must be a tuple of one or two timestamps.")

    if deadline_date is not None:
        # If a deadline is provided, calculate time remaining
        return _get_time_till_deadline(deadline_date)

    if check_if_within_working_hours:
        # If checking working hours, return boolean result as a string
        return _determine_if_current_time_is_within_working_hours()

    # Get current time
    now = datetime.now()

    # Format based on type
    match format_type:
        case "iso":
            return now.isoformat()
        case "human":
            return now.strftime("%Y-%m-%d %H:%M:%S")
        case "timestamp":
            return str(int(now.timestamp()))
        case _:
            # Treat as custom strftime format
            return now.strftime(format_type)
