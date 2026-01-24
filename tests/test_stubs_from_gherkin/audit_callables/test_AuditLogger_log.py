"""
Test stubs for AuditLogger.log()

Tests the log() method of AuditLogger.
This callable logs an audit event with specified level, category, action, and details.
"""

import pytest
import tempfile
import os
from pathlib import Path

from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditHandler, AuditEvent, AuditLevel, AuditCategory
from ..conftest import FixtureError


# Fixtures from Background
@pytest.fixture
def an_auditlogger_instance_is_initialized():
    """
    Given an AuditLogger instance is initialized
    """
    try:
        # Create a fresh AuditLogger instance
        logger = AuditLogger()
        
        # Verify the logger was created successfully
        if logger is None:
            raise FixtureError("Failed to create fixture an_auditlogger_instance_is_initialized: AuditLogger instance is None") from None
        
        # Verify essential attributes exist
        if not hasattr(logger, 'handlers'):
            raise FixtureError("Failed to create fixture an_auditlogger_instance_is_initialized: AuditLogger missing 'handlers' attribute") from None
        
        if not hasattr(logger, 'enabled'):
            raise FixtureError("Failed to create fixture an_auditlogger_instance_is_initialized: AuditLogger missing 'enabled' attribute") from None
        
        return logger
    except Exception as e:
        raise FixtureError(f"Failed to create fixture an_auditlogger_instance_is_initialized: {e}") from e

@pytest.fixture
def the_audit_logger_is_enabled(an_auditlogger_instance_is_initialized):
    """
    Given the audit logger is enabled
    """
    try:
        logger = an_auditlogger_instance_is_initialized
        
        # Enable the audit logger
        logger.enabled = True
        
        # Verify it's actually enabled
        if not logger.enabled:
            raise FixtureError("Failed to create fixture the_audit_logger_is_enabled: Logger enabled flag is not True") from None
        
        return logger
    except Exception as e:
        raise FixtureError(f"Failed to create fixture the_audit_logger_is_enabled: {e}") from e

@pytest.fixture
def at_least_one_audit_handler_is_attached(the_audit_logger_is_enabled):
    """
    Given at least one audit handler is attached
    """
    try:
        logger = the_audit_logger_is_enabled
        
        # Create a simple test handler that stores events
        class TestHandler(AuditHandler):
            def __init__(self):
                super().__init__(name="test_handler")
                self.events = []
            
            def _handle_event(self, event: AuditEvent) -> bool:
                self.events.append(event)
                return True
        
        handler = TestHandler()
        logger.add_handler(handler)
        
        # Verify handler was added
        if len(logger.handlers) == 0:
            raise FixtureError("Failed to create fixture at_least_one_audit_handler_is_attached: No handlers in logger.handlers list") from None
        
        # Verify our handler is in the list
        if handler not in logger.handlers:
            raise FixtureError("Failed to create fixture at_least_one_audit_handler_is_attached: Test handler not found in logger.handlers") from None
        
        # Store handler and events list on logger for easy test access
        logger._test_handler = handler
        logger._events = handler.events
        
        return logger
    except Exception as e:
        raise FixtureError(f"Failed to create fixture at_least_one_audit_handler_is_attached: {e}") from e


def test_log_method_creates_audit_event(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates audit event

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        an AuditEvent is created
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    result_event_id = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result_event_id is not None
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_event_id_attribute(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with event_id attribute

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event has event_id attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'event_id')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_timestamp_attribute(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with timestamp attribute

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event has timestamp attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'timestamp')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_correct_level(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with correct level

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event level is INFO
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.level
    expected_result = AuditLevel.INFO
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_correct_category(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with correct category

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event category is AUTHENTICATION
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.category
    expected_result = AuditCategory.AUTHENTICATION
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_correct_action(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with correct action

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event action is "login"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.action
    expected_result = "login"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_event_id(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns event ID

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read"

    Then:
        a string event_id is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    
    result_event_id = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = isinstance(result_event_id, str)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_valid_uuid_as_event_id(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns valid UUID as event_id

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read"

    Then:
        the event_id is a valid UUID
    """
    import uuid
    
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    
    result_event_id = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    # Attempt to create UUID object from the result
    parsed_uuid = uuid.UUID(result_event_id)
    actual_result = str(parsed_uuid) == result_event_id
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_user_in_event_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes user in event when provided

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read", user="alice"

    Then:
        the created event has user="alice"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    expected_user = "alice"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        user=expected_user
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.user
    expected_result = "alice"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_resource_id_in_event_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes resource_id in event when provided

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read", resource_id="file123"

    Then:
        the created event has resource_id="file123"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    expected_resource_id = "file123"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        resource_id=expected_resource_id
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.resource_id
    expected_result = "file123"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_resource_type_in_event_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes resource_type in event when provided

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read", resource_type="dataset"

    Then:
        the created event has resource_type="dataset"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    expected_resource_type = "dataset"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        resource_type=expected_resource_type
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.resource_type
    expected_result = "dataset"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_status_in_event_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes status in event when provided

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login", status="failure"

    Then:
        the created event has status="failure"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    expected_status = "failure"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        status=expected_status
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.status
    expected_result = "failure"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_details_dictionary_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes details dictionary when provided

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read", details={"file_size": 1024}

    Then:
        the created event has details dictionary
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    expected_details = {"file_size": 1024}
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        details=expected_details
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = isinstance(last_event.details, dict)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_details_with_correct_content(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes details with correct content

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read", details={"file_size": 1024}

    Then:
        details contains key "file_size" with value 1024
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    expected_details = {"file_size": 1024}
    expected_file_size_key = "file_size"
    expected_file_size_value = 1024
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        details=expected_details
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.details.get(expected_file_size_key)
    expected_result = 1024
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_client_ip_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes client_ip when provided

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login", client_ip="192.168.1.1"

    Then:
        the created event has client_ip="192.168.1.1"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    expected_client_ip = "192.168.1.1"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        client_ip=expected_client_ip
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.client_ip
    expected_result = "192.168.1.1"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_includes_session_id_when_provided(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method includes session_id when provided

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login", session_id="sess123"

    Then:
        the created event has session_id="sess123"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    expected_session_id = "sess123"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action,
        session_id=expected_session_id
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.session_id
    expected_result = "sess123"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_applies_thread_local_context_user_to_event(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method applies thread-local context user to event

    Given:
        set_context() was called with user="bob", session_id="sess456"

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read"

    Then:
        the created event has user="bob"
    """
    expected_context_user = "bob"
    expected_context_session_id = "sess456"
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    
    # Set thread-local context first
    at_least_one_audit_handler_is_attached.set_context(user=expected_context_user, session_id=expected_context_session_id)
    
    # Call log without explicit user parameter
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.user
    expected_result = "bob"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_applies_thread_local_context_session_id_to_event(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method applies thread-local context session_id to event

    Given:
        set_context() was called with user="bob", session_id="sess456"

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read"

    Then:
        the created event has session_id="sess456"
    """
    expected_context_user = "bob"
    expected_context_session_id = "sess456"
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    
    # Set thread-local context first
    at_least_one_audit_handler_is_attached.set_context(user=expected_context_user, session_id=expected_context_session_id)
    
    # Call log without explicit session_id parameter
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.session_id
    expected_result = "sess456"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_dispatches_event_to_all_handlers(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method dispatches event to all handlers

    Given:
        3 audit handlers are attached

    When:
        log() is called with level=INFO, category=SYSTEM, action="startup"

    Then:
        all 3 handlers receive the event
    """
    expected_handler_count = 3
    expected_level = AuditLevel.SYSTEM
    expected_category = AuditCategory.SYSTEM
    expected_action = "startup"
    
    # Add 2 more handlers (1 already exists from fixture)
    class TestHandler2(AuditHandler):
        def __init__(self, name):
            super().__init__(name=name)
            self.events = []
        def _handle_event(self, event: AuditEvent) -> bool:
            self.events.append(event)
            return True
    
    handler2 = TestHandler2("handler2")
    handler3 = TestHandler2("handler3")
    at_least_one_audit_handler_is_attached.add_handler(handler2)
    at_least_one_audit_handler_is_attached.add_handler(handler3)
    
    # Call log
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    # Count handlers that received events
    handlers_with_events = sum(1 for h in at_least_one_audit_handler_is_attached.handlers if len(h.events) > 0)
    actual_result = handlers_with_events
    expected_result = 3
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_notifies_event_listeners(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method notifies event listeners

    Given:
        2 event listeners are registered

    When:
        log() is called with level=INFO, category=SECURITY, action="breach"

    Then:
        all 2 listeners are called with the event
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SECURITY
    expected_action = "breach"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._test_listener_calls)
    expected_result = 1
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_none_when_logger_is_disabled(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns None when logger is disabled

    Given:
        the audit logger is disabled

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        None is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.enabled = False
    
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result
    expected_result = None
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_no_event_when_logger_is_disabled(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates no event when logger is disabled

    Given:
        the audit logger is disabled

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        no event is created
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.enabled = False
    initial_event_count = len(at_least_one_audit_handler_is_attached._events)
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._events)
    expected_result = initial_event_count
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_none_when_level_is_below_min_level(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns None when level is below min_level

    Given:
        the audit logger min_level is WARNING

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        None is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.min_level = AuditLevel.WARNING
    
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result
    expected_result = None
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_no_event_when_level_is_below_min_level(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates no event when level is below min_level

    Given:
        the audit logger min_level is WARNING

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        no event is created
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.min_level = AuditLevel.WARNING
    initial_event_count = len(at_least_one_audit_handler_is_attached._events)
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._events)
    expected_result = initial_event_count
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_none_when_category_is_excluded(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns None when category is excluded

    Given:
        category OPERATIONAL is in excluded_categories

    When:
        log() is called with level=INFO, category=OPERATIONAL, action="test"

    Then:
        None is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.OPERATIONAL
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.excluded_categories = [AuditCategory.OPERATIONAL]
    
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result
    expected_result = None
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_no_event_when_category_is_excluded(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates no event when category is excluded

    Given:
        category OPERATIONAL is in excluded_categories

    When:
        log() is called with level=INFO, category=OPERATIONAL, action="test"

    Then:
        no event is created
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.OPERATIONAL
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.excluded_categories = [AuditCategory.OPERATIONAL]
    initial_event_count = len(at_least_one_audit_handler_is_attached._events)
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._events)
    expected_result = initial_event_count
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_returns_none_when_category_not_in_included_categories(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns None when category not in included_categories

    Given:
        included_categories contains only SECURITY

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        None is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.included_categories = [AuditCategory.SECURITY]
    
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result
    expected_result = None
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_no_event_when_category_not_in_included_categories(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates no event when category not in included_categories

    Given:
        included_categories contains only SECURITY

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        no event is created
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    at_least_one_audit_handler_is_attached.included_categories = [AuditCategory.SECURITY]
    initial_event_count = len(at_least_one_audit_handler_is_attached._events)
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._events)
    expected_result = initial_event_count
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_captures_source_module_from_call_stack(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method captures source_module from call stack

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the created event has source_module attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'source_module')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_captures_source_module_not_from_audit_logger(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method captures source_module not from audit_logger

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        source_module is not "audit_logger.py"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.source_module != "audit_logger.py"
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_captures_source_function_from_call_stack(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method captures source_function from call stack

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the created event has source_function attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'source_function')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_captures_non_empty_source_function(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method captures non-empty source_function

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        source_function is a non-empty string
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = len(last_event.source_function) > 0
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_handles_handler_exceptions_gracefully(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method handles handler exceptions gracefully

    Given:
        an audit handler that raises Exception

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the method completes without raising Exception
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    # Create a handler that raises exception
    class FailingHandler(AuditHandler):
        def _handle_event(self, event):
            raise Exception("Handler failure")
    
    failing_handler = FailingHandler()
    at_least_one_audit_handler_is_attached.add_handler(failing_handler)
    
    # Call log - should not raise exception
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = result is not None
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"
    pass


def test_log_method_returns_event_id_despite_handler_exceptions(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method returns event_id despite handler exceptions

    Given:
        an audit handler that raises Exception

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the event_id is returned
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    # Create a handler that raises exception
    class FailingHandler(AuditHandler):
        def _handle_event(self, event):
            raise Exception("Handler failure")
    
    failing_handler = FailingHandler()
    at_least_one_audit_handler_is_attached.add_handler(failing_handler)
    
    result = at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = isinstance(result, str)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_stores_event_in_events_list(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method stores event in events list

    When:
        log() is called with level=INFO, category=AUTHENTICATION, action="login"

    Then:
        the event is appended to the events list
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.AUTHENTICATION
    expected_action = "login"
    
    initial_event_count = len(at_least_one_audit_handler_is_attached._events)
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(at_least_one_audit_handler_is_attached._events)
    expected_result = initial_event_count + 1
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_default_status(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with default status

    When:
        log() is called with level=INFO, category=DATA_ACCESS, action="read"

    Then:
        the created event has status="success"
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.DATA_ACCESS
    expected_action = "read"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = last_event.status
    expected_result = "success"
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_default_hostname(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with default hostname

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the created event has hostname attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'hostname')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_non_empty_hostname(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with non-empty hostname

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        hostname is a non-empty string
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = len(last_event.hostname) > 0
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_default_process_id(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with default process_id

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the created event has process_id attribute
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = hasattr(last_event, 'process_id')
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_log_method_creates_event_with_positive_integer_process_id(an_auditlogger_instance_is_initialized, the_audit_logger_is_enabled, at_least_one_audit_handler_is_attached):
    """
    Scenario: Log method creates event with positive integer process_id

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        process_id is a positive integer
    """
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    at_least_one_audit_handler_is_attached.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    last_event = at_least_one_audit_handler_is_attached._events[-1]
    actual_result = isinstance(last_event.process_id, int) and last_event.process_id > 0
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"

