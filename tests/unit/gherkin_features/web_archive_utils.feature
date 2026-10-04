Feature: Web Archive Utilities
  Utility functions for web archive operations

  Scenario: Parse WARC file
    Given a WARC file
    When parsing is requested
    Then WARC records are extracted

  Scenario: Extract response from WARC
    Given a WARC file and URL
    When response extraction is requested
    Then the HTTP response is returned

  Scenario: Convert WARC to other formats
    Given a WARC file
    When format conversion is requested
    Then the archive is converted to target format

  Scenario: Validate WARC file structure
    Given a WARC file
    When validation is performed
    Then structural correctness is verified

  Scenario: Index WARC file contents
    Given a WARC file
    When indexing is requested
    Then a searchable index is created

  Scenario: Extract metadata from WARC
    Given a WARC file
    When metadata extraction is requested
    Then WARC metadata is returned

  Scenario: Merge multiple WARC files
    Given multiple WARC files
    When merging is requested
    Then a combined WARC file is created

  Scenario: Split large WARC file
    Given a large WARC file
    When splitting is requested
    Then multiple smaller WARC files are created
