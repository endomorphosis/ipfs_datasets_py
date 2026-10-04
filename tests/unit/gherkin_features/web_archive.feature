Feature: Web Archive Processing
  Web content archiving and retrieval functionality

  Scenario: Archive web page
    Given a URL to archive
    When the web page is archived
    Then the page content is stored

  Scenario: Capture web page with assets
    Given a URL and asset capture enabled
    When the web page is archived
    Then the HTML and linked assets are stored

  Scenario: Extract metadata from archived page
    Given an archived web page
    When metadata extraction is requested
    Then page metadata is returned

  Scenario: Retrieve archived page by URL
    Given a previously archived URL
    When the archived page is requested
    Then the stored content is returned

  Scenario: Archive page with timestamp
    Given a URL and current timestamp
    When the page is archived
    Then the archive includes the timestamp

  Scenario: Handle archived page not found
    Given a URL that was not archived
    When the archived page is requested
    Then a not found response is returned

  Scenario: Archive multiple versions of same URL
    Given a URL archived at different times
    When multiple archives are created
    Then each version is stored separately

  Scenario: Extract text from archived HTML
    Given an archived HTML page
    When text extraction is requested
    Then the text content is returned

  Scenario: Capture page screenshots
    Given a URL and screenshot option enabled
    When the page is archived
    Then a screenshot is stored with the archive

  Scenario: Archive page with custom user agent
    Given a URL and custom user agent
    When the page is archived
    Then the request uses the specified user agent

  Scenario: Handle redirect during archiving
    Given a URL that redirects
    When the page is archived
    Then the final destination is archived
