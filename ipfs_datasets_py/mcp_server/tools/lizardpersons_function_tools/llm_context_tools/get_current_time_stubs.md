# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/llm_context_tools/get_current_time.py'

Files last updated: 1748926770.8049743

Stub file last updated: 2025-07-07 01:10:14

## _convert_timestamp_to_datetime

```python
def _convert_timestamp_to_datetime(timestamp: str | int | float) -> datetime:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _determine_if_current_time_is_within_working_hours

```python
def _determine_if_current_time_is_within_working_hours() -> str:
    """
    Determine if the current time is within working hours (9 AM to 5 PM).

Returns:
    str: 'True' if current time is within working hours, 'False' otherwise.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _duration_since

```python
def _duration_since(timestamp: str | int | float) -> str:
    """
    Calculate the duration between a given timestamp and the current time.

Args:
    timestamp: Past timestamp as ISO string, Unix timestamp, or datetime object
    
Returns:
    str: Human-readable duration since timestamp (e.g., "2 days, 3 hours ago")
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_days_hours_minutes_seconds

```python
def _get_days_hours_minutes_seconds(diff: timedelta) -> tuple[int, int, int, int]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_duration

```python
def _get_duration(days: int, hours: int, minutes: int, seconds: int) -> str:
    """
    Format duration into a human-readable string.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_time_till_deadline

```python
def _get_time_till_deadline(deadline: str | int | float) -> str:
    """
    Calculate time remaining until a deadline.

Args:
    deadline: Deadline as ISO string, timestamp, or Unix timestamp
    
Returns:
    str: Human-readable time remaining (e.g., "2 days, 3 hours")
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _time_between

```python
def _time_between(start: str | int | float, end: str | int | float) -> str:
    """
    Get the time difference between two timestamps.

Args:
    start: Start timestamp as ISO string, Unix timestamp, or datetime object
    end: End timestamp as ISO string, Unix timestamp, or datetime object
    
Returns:
    str: Human-readable duration between timestamps (e.g., "2 days, 3 hours")
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_current_time

```python
def get_current_time(format_type: str = "iso", time_between: Optional[tuple[str | int | float, ...]] = None, deadline_date: Optional[str | int | float] = None, check_if_within_working_hours: bool = False) -> str:
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A
