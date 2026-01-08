Feature: FileAuditHandler._handle_event()
  Tests the _handle_event() method of FileAuditHandler.
  This callable writes an audit event to a file.

  Background:
    Given a FileAuditHandler with file_path="/tmp/audit.log" is initialized
    And the handler is enabled
    And the file is opened

  Scenario: Handle event writes formatted event to file
    Given an AuditEvent exists
    When _handle_event() is called
    Then the event is written to file
    And the file contains the formatted event text

  Scenario: Handle event returns True on success
    Given an AuditEvent exists
    When _handle_event() is called
    Then True is returned

  Scenario: Handle event appends newline to formatted event
    Given an AuditEvent exists
    And the formatter does not include newline
    When _handle_event() is called
    Then the written text ends with newline

  Scenario: Handle event flushes file after write
    Given an AuditEvent exists
    When _handle_event() is called
    Then the file flush() method is called

  Scenario: Handle event updates current_size counter
    Given an AuditEvent exists
    And current_size is 1000 bytes
    When _handle_event() is called
    And the formatted event is 100 bytes
    Then current_size is 1100 bytes

  Scenario: Handle event triggers rotation when size exceeded
    Given rotate_size_mb is 1
    And current_size is 1048000 bytes
    When _handle_event() is called with 577 byte event
    Then the file is rotated

  Scenario: Handle event reopens file if closed
    Given the file is closed
    When _handle_event() is called
    Then the file is reopened
    And the event is written

  Scenario: Handle event returns False on file open error
    Given the file_path directory does not exist
    And the file is closed
    When _handle_event() is called
    Then False is returned

  Scenario: Handle event returns False on write error
    Given the file has no write permission
    When _handle_event() is called
    Then False is returned

  Scenario: Handle event handles compression when enabled
    Given use_compression is True
    When _handle_event() is called
    Then the event is written as compressed bytes

  Scenario: Handle event encodes text for compressed files
    Given use_compression is True
    And an AuditEvent exists
    When _handle_event() is called
    Then the event text is encoded to UTF-8 bytes before writing
