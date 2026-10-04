Feature: DeonticExtractor.extract_statements()
  Tests the extract_statements() method of DeonticExtractor.
  This callable extracts deontic statements from text.

  Background:
    Given a DeonticExtractor instance
    And document_id is "doc1"

  Scenario: Extract statements with empty text returns empty list
    When extract_statements() is called with text=""
    Then an empty list is returned

  Scenario: Extract obligation statement with "must"
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extracted obligation has modality OBLIGATION
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement modality is OBLIGATION

  Scenario: Extracted obligation has entity "citizens"
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement entity is "citizens"

  Scenario: Extracted obligation has action "pay taxes"
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement action is "pay taxes"

  Scenario: Extract permission statement with "may"
    Given text is "Citizens may vote."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extracted permission has modality PERMISSION
    Given text is "Citizens may vote."
    When extract_statements() is called
    Then the statement modality is PERMISSION

  Scenario: Extract prohibition statement with "must not"
    Given text is "Citizens must not steal."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extracted prohibition has modality PROHIBITION
    Given text is "Citizens must not steal."
    When extract_statements() is called
    Then the statement modality is PROHIBITION

  Scenario: Extract multiple statements from text
    Given text is "Citizens must pay taxes. Citizens may vote."
    When extract_statements() is called
    Then 2 statements are extracted

  Scenario: Each statement has unique id
    Given text is "Citizens must pay taxes. Citizens may vote."
    When extract_statements() is called
    Then each statement has unique id

  Scenario: Statement id starts with "stmt_"
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement id starts with "stmt_"

  Scenario: Statement has source_document attribute
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement source_document is "doc1"

  Scenario: Statement has source_text attribute
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement source_text contains "must pay taxes"

  Scenario: Statement has confidence attribute
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement confidence is between 0.0 and 1.0

  Scenario: Statement with "must" has confidence >= 0.7
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement confidence is >= 0.7

  Scenario: Statement with "shall" has confidence >= 0.7
    Given text is "Citizens shall pay taxes."
    When extract_statements() is called
    Then the statement confidence is >= 0.7

  Scenario: Statement has context dictionary
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement context is a dictionary

  Scenario: Context has surrounding_text key
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement context has surrounding_text key

  Scenario: Context has position key
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement context has position key

  Scenario: Context has extracted_at timestamp
    Given text is "Citizens must pay taxes."
    When extract_statements() is called
    Then the statement context has extracted_at key

  Scenario: Extract conditional statement with "if"
    Given text is "If citizens earn income, then citizens must file taxes."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extracted conditional has modality CONDITIONAL
    Given text is "If citizens earn income, then citizens must file taxes."
    When extract_statements() is called
    Then the statement modality is CONDITIONAL

  Scenario: Conditional statement has conditions list
    Given text is "If citizens earn income, then citizens must file taxes."
    When extract_statements() is called
    Then the statement conditions list contains 1 entry

  Scenario: Conditional statement id starts with "cond_stmt_"
    Given text is "If citizens earn income, then citizens must file taxes."
    When extract_statements() is called
    Then the statement id starts with "cond_stmt_"

  Scenario: Extract statement with exception
    Given text is "Citizens must pay taxes, unless citizens earn less than threshold."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extracted exception statement has modality EXCEPTION
    Given text is "Citizens must pay taxes, unless citizens earn less than threshold."
    When extract_statements() is called
    Then the statement modality is EXCEPTION

  Scenario: Exception statement has exceptions list
    Given text is "Citizens must pay taxes, unless citizens earn less than threshold."
    When extract_statements() is called
    Then the statement exceptions list contains 1 entry

  Scenario: Exception statement id starts with "exc_stmt_"
    Given text is "Citizens must pay taxes, unless citizens earn less than threshold."
    When extract_statements() is called
    Then the statement id starts with "exc_stmt_"

  Scenario: Extract obligation with "shall"
    Given text is "Employees shall submit reports."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extract obligation with "required to"
    Given text is "Employees are required to submit reports."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extract permission with "can"
    Given text is "Employees can request leave."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extract prohibition with "cannot"
    Given text is "Employees cannot disclose secrets."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Extract prohibition with "forbidden to"
    Given text is "Employees are forbidden to disclose secrets."
    When extract_statements() is called
    Then 1 statement is extracted

  Scenario: Entity is normalized to lowercase
    Given text is "CITIZENS must pay taxes."
    When extract_statements() is called
    Then the statement entity is "citizens"

  Scenario: Action is normalized to lowercase
    Given text is "Citizens must PAY TAXES."
    When extract_statements() is called
    Then the statement action is "pay taxes"

  Scenario: Skip statement with generic entity "it"
    Given text is "It must be done."
    When extract_statements() is called
    Then 0 statements are extracted

  Scenario: Skip statement with generic entity "this"
    Given text is "This must be done."
    When extract_statements() is called
    Then 0 statements are extracted

  Scenario: Skip statement with short action
    Given text is "Citizens must do."
    When extract_statements() is called
    Then 0 statements are extracted

  Scenario: Extract 5 statements from text with mixed modalities
    Given text contains 2 obligations, 2 permissions, and 1 prohibition
    When extract_statements() is called
    Then 5 statements are extracted

  Scenario: Different modality statements have different patterns
    Given text contains obligations, permissions, and prohibitions
    When extract_statements() is called
    Then statements have modalities OBLIGATION, PERMISSION, and PROHIBITION
