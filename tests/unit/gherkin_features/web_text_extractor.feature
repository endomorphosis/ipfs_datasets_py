Feature: Web Text Extraction
  Extract text content from web pages

  Scenario: Extract text from HTML page
    Given an HTML web page
    When text extraction is performed
    Then clean text content is returned

  Scenario: Remove HTML tags
    Given HTML content with tags
    When tag removal is applied
    Then only text content remains

  Scenario: Extract main content
    Given a web page with navigation and ads
    When main content extraction is performed
    Then only article content is returned

  Scenario: Preserve paragraph structure
    Given HTML with paragraphs
    When text extraction is performed
    Then paragraph structure is preserved

  Scenario: Extract metadata
    Given an HTML page with metadata
    When metadata extraction is performed
    Then title, author, and date are extracted

  Scenario: Handle JavaScript-rendered content
    Given a page with JavaScript-rendered content
    When extraction is performed
    Then rendered content is extracted

  Scenario: Clean extracted text
    Given extracted text with extra whitespace
    When text cleaning is applied
    Then normalized text is returned

  Scenario: Extract links from page
    Given an HTML page with links
    When link extraction is performed
    Then all hyperlinks are returned
