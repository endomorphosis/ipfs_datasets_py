"""
Audit Logging Handlers

This module provides various handlers for processing audit events,
such as writing them to files, databases, or sending alerts.
"""

import os
import json
import gzip
import logging
import datetime
import threading
import socket
from typing import Dict, List, Any, Optional, Union, Callable, TextIO, BinaryIO
from pathlib import Path

from ipfs_datasets_py.audit.audit_logger import AuditHandler, AuditEvent, AuditLevel

# Try to import optional dependencies
try:
    import syslog
    SYSLOG_AVAILABLE = True
except ImportError:
    SYSLOG_AVAILABLE = False

try:
    from elasticsearch import Elasticsearch
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False


class FileAuditHandler(AuditHandler):
    """
    Handler that writes audit events to a file.

    Features:
    - Configurable file path with optional rotation
    - Support for text and binary (compressed) files
    - Customizable formatting of events
    """

    def __init__(self, name: str, file_path: str,
                 min_level: AuditLevel = AuditLevel.INFO,
                 formatter: Optional[Callable[[AuditEvent], str]] = None,
                 rotate_size_mb: Optional[float] = None,
                 rotate_count: int = 5,
                 use_compression: bool = False,
                 mode: str = 'a',
                 encoding: str = 'utf-8'):
        """
        Initialize the file audit handler.

        Args:
            name: Name of this handler
            file_path: Path to the audit log file
            min_level: Minimum audit level to process
            formatter: Optional formatter function to convert events to strings
            rotate_size_mb: Maximum file size in MB before rotation (None for no rotation)
            rotate_count: Maximum number of rotated files to keep
            use_compression: Whether to compress rotated files
            mode: File open mode ('a' for append, 'w' for write)
            encoding: File encoding for text files
        """
        super().__init__(name, min_level, formatter)
        self.file_path = file_path
        self.rotate_size_mb = rotate_size_mb
        self.rotate_count = rotate_count
        self.use_compression = use_compression
        self.mode = mode
        self.encoding = encoding
        self._file = None
        self._lock = threading.RLock()
        self._current_size = 0

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Open the file
        self._open_file()

    def _open_file(self) -> None:
        """Open the audit log file."""
        if self.use_compression:
            self._file = gzip.open(self.file_path, f"{self.mode}b")
        else:
            self._file = open(self.file_path, self.mode, encoding=self.encoding)

        # Get current file size
        self._file.seek(0, os.SEEK_END)
        self._current_size = self._file.tell()

    def _rotate_file(self) -> None:
        """Rotate the audit log file if it exceeds the maximum size."""
        # Close current file
        self._file.close()

        # Rename existing rotated files
        for i in range(self.rotate_count - 1, 0, -1):
            old_path = f"{self.file_path}.{i}"
            new_path = f"{self.file_path}.{i+1}"

            if os.path.exists(old_path):
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(old_path, new_path)

        # Rename current file
        if os.path.exists(self.file_path):
            os.rename(self.file_path, f"{self.file_path}.1")

        # Open new file
        self._open_file()

    def _handle_event(self, event: AuditEvent) -> bool:
        """Write the audit event to file."""
        with self._lock:
            if self._file is None or self._file.closed:
                try:
                    self._open_file()
                except Exception as e:
                    logging.error(f"Error opening audit log file: {str(e)}")
                    return False

            try:
                # Format the event
                formatted_event = self.format_event(event)
                if not formatted_event.endswith('\n'):
                    formatted_event += '\n'

                # Write to file
                if self.use_compression:
                    self._file.write(formatted_event.encode('utf-8'))
                else:
                    self._file.write(formatted_event)

                self._file.flush()

                # Update current size and check rotation
                self._current_size += len(formatted_event)
                if (self.rotate_size_mb is not None and
                    self._current_size > self.rotate_size_mb * 1024 * 1024):
                    self._rotate_file()

                return True

            except Exception as e:
                logging.error(f"Error writing to audit log file: {str(e)}")
                return False

    def close(self) -> None:
        """Close the file handler."""
        with self._lock:
            if self._file and not self._file.closed:
                self._file.close()
                self._file = None


class JSONAuditHandler(AuditHandler):
    """
    Handler that writes audit events as JSON objects.

    Features:
    - One JSON object per line (JSON Lines format)
    - Optional pretty printing for human readability
    - Support for writing to file or any file-like object
    """

    def __init__(self, name: str, file_path: Optional[str] = None,
                 file_obj: Optional[TextIO] = None,
                 min_level: AuditLevel = AuditLevel.INFO,
                 pretty: bool = False,
                 rotate_size_mb: Optional[float] = None,
                 rotate_count: int = 5,
                 use_compression: bool = False):
        """
        Initialize the JSON audit handler.

        Args:
            name: Name of this handler
            file_path: Path to the audit log file (mutually exclusive with file_obj)
            file_obj: File-like object to write to (mutually exclusive with file_path)
            min_level: Minimum audit level to process
            pretty: Whether to pretty-print JSON for human readability
            rotate_size_mb: Maximum file size in MB before rotation (None for no rotation)
            rotate_count: Maximum number of rotated files to keep
            use_compression: Whether to compress rotated files
        """
        super().__init__(name, min_level)

        if file_path and file_obj:
            raise ValueError("Cannot specify both file_path and file_obj")

        self.file_path = file_path
        self.file_obj = file_obj
        self.pretty = pretty
        self.rotate_size_mb = rotate_size_mb
        self.rotate_count = rotate_count
        self.use_compression = use_compression
        self._file = None
        self._lock = threading.RLock()
        self._current_size = 0
        self._owns_file = file_obj is None

        # Create file if using file_path
        if file_path:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            self._open_file()
        else:
            self._file = file_obj

    def _open_file(self) -> None:
        """Open the audit log file."""
        if self.use_compression:
            self._file = gzip.open(self.file_path, "ab")
        else:
            self._file = open(self.file_path, "a", encoding="utf-8")

        # Get current file size
        self._file.seek(0, os.SEEK_END)
        self._current_size = self._file.tell()

    def _rotate_file(self) -> None:
        """Rotate the audit log file if it exceeds the maximum size."""
        if not self._owns_file:
            return  # Can't rotate a file we don't own

        # Close current file
        self._file.close()

        # Rename existing rotated files
        for i in range(self.rotate_count - 1, 0, -1):
            old_path = f"{self.file_path}.{i}"
            new_path = f"{self.file_path}.{i+1}"

            if os.path.exists(old_path):
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(old_path, new_path)

        # Rename current file
        if os.path.exists(self.file_path):
            os.rename(self.file_path, f"{self.file_path}.1")

        # Open new file
        self._open_file()

    def _handle_event(self, event: AuditEvent) -> bool:
        """Write the audit event as JSON."""
        with self._lock:
            if self._file is None or (hasattr(self._file, 'closed') and self._file.closed):
                if not self._owns_file:
                    return False  # Can't reopen a file we don't own

                try:
                    self._open_file()
                except Exception as e:
                    logging.error(f"Error opening audit log file: {str(e)}")
                    return False

            try:
                # Convert event to JSON
                if self.pretty:
                    json_str = event.to_json(pretty=True)
                else:
                    json_str = event.to_json()

                if not json_str.endswith('\n'):
                    json_str += '\n'

                # Write to file
                if isinstance(self._file, gzip.GzipFile):
                    self._file.write(json_str.encode('utf-8'))
                else:
                    self._file.write(json_str)

                self._file.flush()

                # Update current size and check rotation
                if self._owns_file:
                    self._current_size += len(json_str)
                    if (self.rotate_size_mb is not None and
                        self._current_size > self.rotate_size_mb * 1024 * 1024):
                        self._rotate_file()

                return True

            except Exception as e:
                logging.error(f"Error writing to JSON audit log: {str(e)}")
                return False

    def close(self) -> None:
        """Close the file handler if we own it."""
        with self._lock:
            if self._owns_file and self._file and hasattr(self._file, 'closed') and not self._file.closed:
                self._file.close()
                self._file = None


class SyslogAuditHandler(AuditHandler):
    """
    Handler that sends audit events to syslog.

    Features:
    - Maps audit levels to syslog priorities
    - Configurable facility and identity
    - Works on Unix-like systems with syslog support
    """

    # Map audit levels to syslog priorities
    LEVEL_MAP = {
        AuditLevel.DEBUG: syslog.LOG_DEBUG if SYSLOG_AVAILABLE else 7,
        AuditLevel.INFO: syslog.LOG_INFO if SYSLOG_AVAILABLE else 6,
        AuditLevel.NOTICE: syslog.LOG_NOTICE if SYSLOG_AVAILABLE else 5,
        AuditLevel.WARNING: syslog.LOG_WARNING if SYSLOG_AVAILABLE else 4,
        AuditLevel.ERROR: syslog.LOG_ERR if SYSLOG_AVAILABLE else 3,
        AuditLevel.CRITICAL: syslog.LOG_CRIT if SYSLOG_AVAILABLE else 2,
        AuditLevel.EMERGENCY: syslog.LOG_EMERG if SYSLOG_AVAILABLE else 0
    }

    def __init__(self, name: str, min_level: AuditLevel = AuditLevel.INFO,
                 formatter: Optional[Callable[[AuditEvent], str]] = None,
                 facility: int = None,
                 identity: str = "ipfs_datasets_audit"):
        """
        Initialize the syslog audit handler.

        Args:
            name: Name of this handler
            min_level: Minimum audit level to process
            formatter: Optional formatter function to convert events to strings
            facility: Syslog facility to use
            identity: Identity string for syslog
        """
        super().__init__(name, min_level, formatter)

        if not SYSLOG_AVAILABLE:
            logging.warning("Syslog is not available; SyslogAuditHandler will not function")
            self.enabled = False
            return

        self.identity = identity
        self.facility = facility or syslog.LOG_USER

        # Open syslog connection
        syslog.openlog(ident=identity, facility=self.facility)

    def _handle_event(self, event: AuditEvent) -> bool:
        """Send the audit event to syslog."""
        if not SYSLOG_AVAILABLE:
            return False

        try:
            # Map audit level to syslog priority
            priority = self.LEVEL_MAP.get(event.level, syslog.LOG_NOTICE)

            # Format the event
            formatted_event = self.format_event(event)

            # Send to syslog
            syslog.syslog(priority, formatted_event)
            return True

        except Exception as e:
            logging.error(f"Error sending to syslog: {str(e)}")
            return False

    def close(self) -> None:
        """Close the syslog connection."""
        if SYSLOG_AVAILABLE:
            syslog.closelog()


class ElasticsearchAuditHandler(AuditHandler):
    """
    Handler that sends audit events to Elasticsearch.

    Features:
    - Stores events in Elasticsearch for powerful search and visualization
    - Support for index naming based on date patterns
    - Configurable connection parameters and authentication
    """

    def __init__(self, name: str, hosts: List[str],
                 min_level: AuditLevel = AuditLevel.INFO,
                 index_pattern: str = "audit-logs-{date}",
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 api_key: Optional[Union[str, tuple]] = None,
                 bulk_size: int = 100,
                 bulk_timeout: float = 5.0,
                 **kwargs):
        """
        Initialize the Elasticsearch audit handler.

        Args:
            name: Name of this handler
            hosts: List of Elasticsearch hosts
            min_level: Minimum audit level to process
            index_pattern: Index name pattern with optional {date} placeholder
            username: Optional username for authentication
            password: Optional password for authentication
            api_key: Optional API key for authentication
            bulk_size: Number of events to batch before sending
            bulk_timeout: Maximum time to wait before sending incomplete batch
            **kwargs: Additional arguments for Elasticsearch client
        """
        super().__init__(name, min_level)

        if not ELASTICSEARCH_AVAILABLE:
            logging.warning("Elasticsearch is not available; ElasticsearchAuditHandler will not function")
            self.enabled = False
            return

        self.hosts = hosts
        self.index_pattern = index_pattern
        self.bulk_size = bulk_size
        self.bulk_timeout = bulk_timeout

        # Authentication options
        self.username = username
        self.password = password
        self.api_key = api_key
        self.es_kwargs = kwargs

        # Bulk indexing state
        self._buffer = []
        self._lock = threading.RLock()
        self._last_flush_time = datetime.datetime.now()
        self._es_client = None

        # Connect to Elasticsearch
        self._connect()

    def _connect(self) -> None:
        """Connect to Elasticsearch."""
        try:
            auth_kwargs = {}
            if self.username and self.password:
                auth_kwargs["http_auth"] = (self.username, self.password)
            if self.api_key:
                auth_kwargs["api_key"] = self.api_key

            self._es_client = Elasticsearch(self.hosts, **auth_kwargs, **self.es_kwargs)
            logging.info(f"Connected to Elasticsearch: {self.hosts}")

        except Exception as e:
            logging.error(f"Error connecting to Elasticsearch: {str(e)}")
            self._es_client = None

    def _get_index_name(self) -> str:
        """Get the current index name based on pattern."""
        if "{date}" in self.index_pattern:
            date_str = datetime.datetime.now().strftime("%Y.%m.%d")
            return self.index_pattern.replace("{date}", date_str)
        return self.index_pattern

    def _flush_buffer(self) -> bool:
        """Flush the event buffer to Elasticsearch."""
        if not self._buffer:
            return True

        if not self._es_client:
            try:
                self._connect()
                if not self._es_client:
                    return False
            except Exception:
                return False

        try:
            # Prepare bulk request
            bulk_data = []
            for event in self._buffer:
                index_name = self._get_index_name()
                bulk_data.append({"index": {"_index": index_name}})
                bulk_data.append(event.to_dict())

            # Send bulk request
            response = self._es_client.bulk(body=bulk_data, refresh=True)

            # Check for errors
            if response.get("errors", False):
                errors = [item["index"]["error"] for item in response["items"] if "error" in item["index"]]
                logging.error(f"Errors in Elasticsearch bulk indexing: {errors}")
                return False

            # Clear buffer
            self._buffer = []
            self._last_flush_time = datetime.datetime.now()
            return True

        except Exception as e:
            logging.error(f"Error in Elasticsearch bulk indexing: {str(e)}")
            return False

    def _handle_event(self, event: AuditEvent) -> bool:
        """Send the audit event to Elasticsearch."""
        if not ELASTICSEARCH_AVAILABLE:
            return False

        with self._lock:
            # Add event to buffer
            self._buffer.append(event)

            # Check if we should flush
            should_flush = len(self._buffer) >= self.bulk_size
            time_since_last_flush = (datetime.datetime.now() - self._last_flush_time).total_seconds()
            should_flush = should_flush or (self._buffer and time_since_last_flush >= self.bulk_timeout)

            if should_flush:
                return self._flush_buffer()

            return True

    def close(self) -> None:
        """Flush remaining events and close the Elasticsearch connection."""
        with self._lock:
            self._flush_buffer()
            if self._es_client:
                self._es_client.close()
                self._es_client = None


class AlertingAuditHandler(AuditHandler):
    """
    Handler that triggers alerts for security-relevant audit events.

    Features:
    - Configurable alert thresholds and rules
    - Multiple alert destinations (email, webhook, etc.)
    - Rate limiting to prevent alert storms
    - Alert aggregation for related events
    """

    def __init__(self, name: str, min_level: AuditLevel = AuditLevel.WARNING,
                 alert_handlers: Optional[List[Callable[[AuditEvent], None]]] = None,
                 rate_limit_seconds: float = 60.0,
                 aggregation_window_seconds: float = 300.0,
                 alert_rules: Optional[List[Dict[str, Any]]] = None):
        """
        Initialize the alerting audit handler.

        Args:
            name: Name of this handler
            min_level: Minimum audit level to trigger alerts
            alert_handlers: List of handler functions for sending alerts
            rate_limit_seconds: Minimum time between alerts of the same type
            aggregation_window_seconds: Time window for aggregating similar alerts
            alert_rules: List of rules for determining when to alert
        """
        super().__init__(name, min_level)
        self.alert_handlers = alert_handlers or []
        self.rate_limit_seconds = rate_limit_seconds
        self.aggregation_window_seconds = aggregation_window_seconds
        self.alert_rules = alert_rules or []

        # State for rate limiting and aggregation
        self._last_alerts = {}  # type -> timestamp
        self._aggregated_events = {}  # rule_id -> [events]
        self._lock = threading.RLock()

    def add_alert_handler(self, handler: Callable[[AuditEvent], None]) -> None:
        """
        Add a handler function for sending alerts.

        Args:
            handler: Function that takes an AuditEvent and sends an alert
        """
        with self._lock:
            self.alert_handlers.append(handler)

    def add_alert_rule(self, rule: Dict[str, Any]) -> None:
        """
        Add a rule for determining when to alert.

        Args:
            rule: Rule specification (e.g., {"category": "AUTHENTICATION", "action": "login_failed", "min_count": 5})
        """
        with self._lock:
            self.alert_rules.append(rule)

    def _check_rate_limit(self, alert_type: str) -> bool:
        """
        Check if an alert of the given type is rate-limited.

        Args:
            alert_type: Type of alert to check

        Returns:
            bool: Whether the alert is allowed (not rate-limited)
        """
        now = datetime.datetime.now()
        if alert_type in self._last_alerts:
            last_time = self._last_alerts[alert_type]
            elapsed = (now - last_time).total_seconds()
            if elapsed < self.rate_limit_seconds:
                return False

        self._last_alerts[alert_type] = now
        return True

    def _match_rule(self, event: AuditEvent, rule: Dict[str, Any]) -> bool:
        """
        Check if an event matches a rule.

        Args:
            event: The audit event to check
            rule: Rule specification

        Returns:
            bool: Whether the event matches the rule
        """
        # Check all conditions in the rule
        for key, value in rule.items():
            if key == "min_count" or key == "window_seconds" or key == "rule_id":
                continue  # These are rule metadata, not match conditions

            if key == "level_min":
                if event.level.value < AuditLevel[value].value:
                    return False
                continue

            if key == "level_max":
                if event.level.value > AuditLevel[value].value:
                    return False
                continue

            if key == "details" and isinstance(value, dict):
                # Match against nested fields in details
                for detail_key, detail_value in value.items():
                    if detail_key not in event.details or event.details[detail_key] != detail_value:
                        return False
                continue

            # Get the attribute from the event
            event_value = getattr(event, key, None)
            if event_value is None:
                return False

            # For enums, compare the names
            if isinstance(event_value, Enum):
                event_value = event_value.name

            # Convert lists to sets for comparison
            if isinstance(value, list):
                if not isinstance(event_value, list) and event_value not in value:
                    return False
                if isinstance(event_value, list) and not set(event_value).intersection(set(value)):
                    return False
                continue

            # Simple equality check
            if event_value != value:
                return False

        return True

    def _process_aggregation(self, event: AuditEvent) -> List[AuditEvent]:
        """
        Process event aggregation according to rules.

        Args:
            event: The audit event to process

        Returns:
            List[AuditEvent]: Events that should trigger alerts
        """
        now = datetime.datetime.now()
        result = []

        # Check each rule for matches and aggregation
        for rule in self.alert_rules:
            if not self._match_rule(event, rule):
                continue

            # Get rule metadata
            rule_id = rule.get("rule_id", f"{event.category.name}_{event.action}")
            min_count = rule.get("min_count", 1)
            window_seconds = rule.get("window_seconds", self.aggregation_window_seconds)

            # Initialize or clean up aggregation bucket
            if rule_id not in self._aggregated_events:
                self._aggregated_events[rule_id] = []
            else:
                # Remove events outside the time window
                cutoff_time = now - datetime.timedelta(seconds=window_seconds)
                self._aggregated_events[rule_id] = [
                    e for e in self._aggregated_events[rule_id]
                    if datetime.datetime.fromisoformat(e.timestamp.rstrip('Z')) > cutoff_time
                ]

            # Add the current event
            self._aggregated_events[rule_id].append(event)

            # Check if we've hit the threshold
            if len(self._aggregated_events[rule_id]) >= min_count:
                # Create an alert type based on the rule
                alert_type = f"{rule_id}_threshold"

                # Check rate limiting
                if self._check_rate_limit(alert_type):
                    # Return all aggregated events for this rule
                    result.extend(self._aggregated_events[rule_id])
                    # Clear the aggregation bucket
                    self._aggregated_events[rule_id] = []

        return result

    def _handle_event(self, event: AuditEvent) -> bool:
        """Process the audit event and send alerts if needed."""
        with self._lock:
            try:
                # Simple level-based alerting for high-severity events
                if event.level.value >= AuditLevel.ERROR.value:
                    alert_type = f"{event.category.name}_{event.action}"
                    if self._check_rate_limit(alert_type):
                        for handler in self.alert_handlers:
                            handler(event)

                # Rule-based alerting with aggregation
                alert_events = self._process_aggregation(event)
                for alert_event in alert_events:
                    for handler in self.alert_handlers:
                        handler(alert_event)

                return True

            except Exception as e:
                logging.error(f"Error in alerting handler: {str(e)}")
                return False

    def close(self) -> None:
        """Clean up resources."""
        with self._lock:
            self._last_alerts = {}
            self._aggregated_events = {}
