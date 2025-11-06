Feature: Enhanced Multimodal Processor
  Enhanced processing for multiple media types

  Scenario: Process mixed media document
    Given a document with text, images, and tables
    When multimodal processing is applied
    Then all content types are extracted

  Scenario: Align text and image content
    Given text and related images
    When content alignment is performed
    Then text-image relationships are identified

  Scenario: Extract information from tables
    Given a document with tables
    When table extraction is performed
    Then structured table data is extracted

  Scenario: Generate cross-modal embeddings
    Given text and visual content
    When cross-modal embedding is requested
    Then unified embeddings are generated

  Scenario: Perform visual question answering
    Given an image and question
    When visual QA is requested
    Then an answer based on image content is generated

  Scenario: Extract text from complex layouts
    Given a document with complex layout
    When layout-aware extraction is performed
    Then text with structure is extracted

  Scenario: Combine audio and visual information
    Given video with audio
    When multimodal fusion is applied
    Then combined features are extracted

  Scenario: Generate multimodal summaries
    Given mixed media content
    When summarization is requested
    Then a summary incorporating all modalities is generated
