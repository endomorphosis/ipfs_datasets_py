"""
Test stubs for AuditLogger.add_handler()

Tests the add_handler() method of AuditLogger.
This callable adds a handler to the audit logger for processing audit events.
"""

import pytest

from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditHandler, AuditEvent
from ..conftest import FixtureError


# Fixtures from Background
@pytest.fixture
def an_auditlogger_instance_is_initialized():
    """
    Given an AuditLogger instance is initialized
    """
    try:
        logger = AuditLogger()
        
        if logger is None:
            raise FixtureError("Failed to create fixture an_auditlogger_instance_is_initialized: AuditLogger instance is None") from None
        
        if not hasattr(logger, 'handlers'):
            raise FixtureError("Failed to create fixture an_auditlogger_instance_is_initialized: AuditLogger missing 'handlers' attribute") from None
        
        return logger
    except Exception as e:
        raise FixtureError(f"Failed to create fixture an_auditlogger_instance_is_initialized: {e}") from e

@pytest.fixture
def the_handlers_list_is_empty(an_auditlogger_instance_is_initialized):
    """
    Given the handlers list is empty
    """
    try:
        logger = an_auditlogger_instance_is_initialized
        
        # Clear any existing handlers
        logger.handlers = []
        
        # Verify handlers list is empty
        if len(logger.handlers) != 0:
            raise FixtureError(f"Failed to create fixture the_handlers_list_is_empty: Handlers list has {len(logger.handlers)} items, expected 0") from None
        
        return logger
    except Exception as e:
        raise FixtureError(f"Failed to create fixture the_handlers_list_is_empty: {e}") from e


def test_add_handler_increases_handlers_count(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler increases handlers count

    Given:
        a FileAuditHandler instance exists

    When:
        add_handler() is called with the handler

    Then:
        the handlers list contains 1 handler
    """
    # Create test handler
    class TestHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    test_handler = TestHandler()
    
    the_handlers_list_is_empty.add_handler(test_handler)
    
    actual_result = len(the_handlers_list_is_empty.handlers)
    expected_result = 1
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_appends_to_handlers_list(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler appends to handlers list

    Given:
        a FileAuditHandler instance exists

    When:
        add_handler() is called with the handler

    Then:
        the handler is in the handlers list
    """
    # Create test handler
    class TestHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    test_handler = TestHandler()
    
    the_handlers_list_is_empty.add_handler(test_handler)
    
    actual_result = test_handler in the_handlers_list_is_empty.handlers
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_allows_multiple_handlers(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler allows multiple handlers

    Given:
        3 different AuditHandler instances exist

    When:
        add_handler() is called for each handler

    Then:
        the handlers list contains 3 handlers
    """
    # Create 3 test handlers
    class TestHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    handler1 = TestHandler()
    handler2 = TestHandler()
    handler3 = TestHandler()
    
    the_handlers_list_is_empty.add_handler(handler1)
    the_handlers_list_is_empty.add_handler(handler2)
    the_handlers_list_is_empty.add_handler(handler3)
    
    actual_result = len(the_handlers_list_is_empty.handlers)
    expected_result = 3
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_allows_handlers_of_different_types_has_2_handlers(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler allows handlers of different types has 2 handlers

    Given:
        a FileAuditHandler exists
        a JSONAuditHandler exists

    When:
        add_handler() is called for both handlers

    Then:
        the handlers list contains 2 handlers
    """
    # Create 2 different handler types
    class FileHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    class JSONHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    file_handler = FileHandler()
    json_handler = JSONHandler()
    
    the_handlers_list_is_empty.add_handler(file_handler)
    the_handlers_list_is_empty.add_handler(json_handler)
    
    actual_result = len(the_handlers_list_is_empty.handlers)
    expected_result = 2
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_allows_handlers_of_different_types_includes_fileaudithandler(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler allows handlers of different types includes FileAuditHandler

    Given:
        a FileAuditHandler exists
        a JSONAuditHandler exists

    When:
        add_handler() is called for both handlers

    Then:
        one handler is FileAuditHandler type
    """
    # Create 2 different handler types
    class FileHandler(AuditHandler):
        handler_type = "file"
        def _handle_event(self, event):
            pass
    
    class JSONHandler(AuditHandler):
        handler_type = "json"
        def _handle_event(self, event):
            pass
    
    file_handler = FileHandler()
    json_handler = JSONHandler()
    
    the_handlers_list_is_empty.add_handler(file_handler)
    the_handlers_list_is_empty.add_handler(json_handler)
    
    actual_result = any(isinstance(h, FileHandler) for h in the_handlers_list_is_empty.handlers)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_allows_handlers_of_different_types_includes_jsonaudithandler(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler allows handlers of different types includes JSONAuditHandler

    Given:
        a FileAuditHandler exists
        a JSONAuditHandler exists

    When:
        add_handler() is called for both handlers

    Then:
        one handler is JSONAuditHandler type
    """
    # Create 2 different handler types
    class FileHandler(AuditHandler):
        handler_type = "file"
        def _handle_event(self, event):
            pass
    
    class JSONHandler(AuditHandler):
        handler_type = "json"
        def _handle_event(self, event):
            pass
    
    file_handler = FileHandler()
    json_handler = JSONHandler()
    
    the_handlers_list_is_empty.add_handler(file_handler)
    the_handlers_list_is_empty.add_handler(json_handler)
    
    actual_result = any(isinstance(h, JSONHandler) for h in the_handlers_list_is_empty.handlers)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_is_thread_safe(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler is thread-safe

    Given:
        10 threads call add_handler() concurrently

    When:
        all threads complete

    Then:
        the handlers list contains 10 handlers
    """
    import threading
    
    # Create 10 handlers
    handlers = []
    for i in range(10):
        class TestHandler(AuditHandler):
            def _handle_event(self, event):
                pass
        handlers.append(TestHandler())
    
    # Add handlers in threads
    threads = []
    for handler in handlers:
        thread = threading.Thread(target=the_handlers_list_is_empty.add_handler, args=(handler,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    actual_result = len(the_handlers_list_is_empty.handlers)
    expected_result = 10
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_accepts_custom_handler_subclass(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler accepts custom handler subclass

    Given:
        a custom AuditHandler subclass instance exists

    When:
        add_handler() is called with the custom handler

    Then:
        the handler is in the handlers list
    """
    # Create custom handler subclass
    class CustomHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    custom_handler = CustomHandler()
    
    the_handlers_list_is_empty.add_handler(custom_handler)
    
    actual_result = custom_handler in the_handlers_list_is_empty.handlers
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_added_handler_receives_subsequent_events(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Added handler receives subsequent events

    Given:
        a FileAuditHandler is added

    When:
        log() is called with level=INFO, category=SYSTEM, action="test"

    Then:
        the FileAuditHandler receives the event
    """
    from ipfs_datasets_py.audit.audit_logger import AuditLevel, AuditCategory
    
    # Create handler that stores events
    class TestHandler(AuditHandler):
        def __init__(self):
            super().__init__()
            self.events = []
        
        def _handle_event(self, event):
            self.events.append(event)
    
    test_handler = TestHandler()
    the_handlers_list_is_empty.add_handler(test_handler)
    the_handlers_list_is_empty.enabled = True
    
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    expected_action = "test"
    
    the_handlers_list_is_empty.log(
        level=expected_level,
        category=expected_category,
        action=expected_action
    )
    
    actual_result = len(test_handler.events)
    expected_result = 1
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_does_not_affect_existing_events(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler does not affect existing events

    Given:
        log() is called with level=INFO, category=SYSTEM, action="before"

    When:
        add_handler() is called with a FileAuditHandler

    Then:
        the FileAuditHandler receives only the "after" event
    """
    from ipfs_datasets_py.audit.audit_logger import AuditLevel, AuditCategory
    
    # Create handler that stores events
    class TestHandler(AuditHandler):
        def __init__(self):
            super().__init__()
            self.events = []
        
        def _handle_event(self, event):
            self.events.append(event)
    
    the_handlers_list_is_empty.enabled = True
    
    # Log before adding handler
    expected_level = AuditLevel.INFO
    expected_category = AuditCategory.SYSTEM
    before_action = "before"
    
    the_handlers_list_is_empty.log(
        level=expected_level,
        category=expected_category,
        action=before_action
    )
    
    # Add handler
    test_handler = TestHandler()
    the_handlers_list_is_empty.add_handler(test_handler)
    
    actual_result = len(test_handler.events)
    expected_result = 0
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_with_same_name_twice_adds_both_handlers(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler with same name twice adds both handlers

    Given:
        a FileAuditHandler with name="handler1" is added

    When:
        add_handler() is called with another handler named "handler1"

    Then:
        the handlers list contains 2 handlers
    """
    # Create 2 handlers with same name
    class TestHandler(AuditHandler):
        def __init__(self, name):
            super().__init__()
            self.name = name
        
        def _handle_event(self, event):
            pass
    
    handler1 = TestHandler("handler1")
    handler2 = TestHandler("handler1")
    
    the_handlers_list_is_empty.add_handler(handler1)
    the_handlers_list_is_empty.add_handler(handler2)
    
    actual_result = len(the_handlers_list_is_empty.handlers)
    expected_result = 2
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_with_same_name_twice_both_have_same_name(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler with same name twice both have same name

    Given:
        a FileAuditHandler with name="handler1" is added

    When:
        add_handler() is called with another handler named "handler1"

    Then:
        both handlers have name="handler1"
    """
    # Create 2 handlers with same name
    class TestHandler(AuditHandler):
        def __init__(self, name):
            super().__init__()
            self.name = name
        
        def _handle_event(self, event):
            pass
    
    expected_name = "handler1"
    handler1 = TestHandler(expected_name)
    handler2 = TestHandler(expected_name)
    
    the_handlers_list_is_empty.add_handler(handler1)
    the_handlers_list_is_empty.add_handler(handler2)
    
    actual_result = all(h.name == expected_name for h in the_handlers_list_is_empty.handlers)
    expected_result = True
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"


def test_add_handler_preserves_handler_configuration(an_auditlogger_instance_is_initialized, the_handlers_list_is_empty):
    """
    Scenario: Add handler preserves handler configuration

    Given:
        a FileAuditHandler with min_level=ERROR exists

    When:
        add_handler() is called with the handler

    Then:
        the handler in list has min_level=ERROR
    """
    from ipfs_datasets_py.audit.audit_logger import AuditLevel
    
    # Create handler with specific configuration
    class TestHandler(AuditHandler):
        def _handle_event(self, event):
            pass
    
    test_handler = TestHandler()
    expected_min_level = AuditLevel.ERROR
    test_handler.min_level = expected_min_level
    
    the_handlers_list_is_empty.add_handler(test_handler)
    
    actual_result = the_handlers_list_is_empty.handlers[0].min_level
    expected_result = AuditLevel.ERROR
    assert actual_result == expected_result, f"expected {expected_result}, got {actual_result}"

