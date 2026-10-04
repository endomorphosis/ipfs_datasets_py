Feature: Advanced Web Archiving
  Enhanced web content archiving capabilities

  Scenario: Archive website with full rendering
    Given a URL requiring JavaScript rendering
    When full rendering archive is requested
    Then the rendered page is archived

  Scenario: Capture website screenshots
    Given a URL
    When screenshot capture is enabled
    Then page screenshots are stored

  Scenario: Archive linked resources
    Given a web page with linked resources
    When deep archiving is performed
    Then all linked resources are archived

  Scenario: Create WARC archive
    Given web pages to archive
    When WARC format is specified
    Then a WARC file is created

  Scenario: Archive website periodically
    Given a URL and schedule
    When scheduled archiving is configured
    Then the site is archived on schedule

  Scenario: Compare archived versions
    Given multiple archive versions
    When comparison is requested
    Then differences between versions are identified

  Scenario: Extract structured data from archive
    Given an archived page with structured data
    When extraction is performed
    Then structured data is extracted

  Scenario: Replay archived page
    Given an archived page
    When replay is requested
    Then the page is reconstructed and displayed
