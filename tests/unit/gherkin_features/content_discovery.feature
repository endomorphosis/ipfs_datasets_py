Feature: Content Discovery
  Discover and index content across sources

  Scenario: Discover content from source
    Given a content source
    When discovery is initiated
    Then available content is identified

  Scenario: Index discovered content
    Given discovered content items
    When indexing is performed
    Then content is added to search index

  Scenario: Monitor source for new content
    Given a monitored content source
    When monitoring runs
    Then new content is detected

  Scenario: Deduplicate discovered content
    Given duplicate content items
    When deduplication is applied
    Then only unique items are retained

  Scenario: Categorize discovered content
    Given discovered content items
    When categorization is performed
    Then content is assigned to categories

  Scenario: Extract metadata from content
    Given a content item
    When metadata extraction is performed
    Then content metadata is extracted

  Scenario: Schedule content discovery
    Given discovery schedule settings
    When scheduling is configured
    Then discovery runs on schedule

  Scenario: Filter content by criteria
    Given filtering criteria
    When discovery runs
    Then only matching content is discovered
