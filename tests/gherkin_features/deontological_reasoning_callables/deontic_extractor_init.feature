Feature: DeonticExtractor.__init__()
  Tests the __init__() method of DeonticExtractor.
  This callable initializes a deontic statement extractor.

  Scenario: Initialize creates DeonticExtractor instance
    When DeonticExtractor() is called
    Then a DeonticExtractor instance is returned

  Scenario: Initialize sets patterns attribute
    When DeonticExtractor() is called
    Then the patterns attribute is set

  Scenario: Initialize sets statement_counter to 0
    When DeonticExtractor() is called
    Then the statement_counter attribute is 0

  Scenario: Patterns attribute is DeonticPatterns instance
    When DeonticExtractor() is called
    Then the patterns attribute is DeonticPatterns instance

  Scenario: Patterns has OBLIGATION_PATTERNS list
    When DeonticExtractor() is called
    Then patterns.OBLIGATION_PATTERNS is a list

  Scenario: Patterns has PERMISSION_PATTERNS list
    When DeonticExtractor() is called
    Then patterns.PERMISSION_PATTERNS is a list

  Scenario: Patterns has PROHIBITION_PATTERNS list
    When DeonticExtractor() is called
    Then patterns.PROHIBITION_PATTERNS is a list

  Scenario: Patterns has CONDITIONAL_PATTERNS list
    When DeonticExtractor() is called
    Then patterns.CONDITIONAL_PATTERNS is a list

  Scenario: Patterns has EXCEPTION_PATTERNS list
    When DeonticExtractor() is called
    Then patterns.EXCEPTION_PATTERNS is a list

  Scenario: OBLIGATION_PATTERNS contains pattern for "must"
    When DeonticExtractor() is called
    Then patterns.OBLIGATION_PATTERNS contains pattern matching "must"

  Scenario: PERMISSION_PATTERNS contains pattern for "may"
    When DeonticExtractor() is called
    Then patterns.PERMISSION_PATTERNS contains pattern matching "may"

  Scenario: PROHIBITION_PATTERNS contains pattern for "must not"
    When DeonticExtractor() is called
    Then patterns.PROHIBITION_PATTERNS contains pattern matching "must not"

  Scenario: Statement counter increments after extraction
    Given a DeonticExtractor instance
    When extract_statements() is called with text containing 2 statements
    Then the statement_counter is 2

  Scenario: Multiple extractions increment counter correctly
    Given a DeonticExtractor instance
    When extract_statements() is called 3 times with 1 statement each
    Then the statement_counter is 3
