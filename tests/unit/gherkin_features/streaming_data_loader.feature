Feature: Streaming Data Loader
  Efficient loading and streaming of large datasets

  Scenario: Initialize streaming loader
    Given a data source
    When the streaming loader is initialized
    Then the loader is ready to stream data

  Scenario: Stream data in batches
    Given a streaming loader with batch size
    When data streaming starts
    Then data is yielded in batches

  Scenario: Load data with memory constraint
    Given a memory limit
    When data is loaded
    Then memory usage stays within limit

  Scenario: Handle compressed data stream
    Given a compressed data source
    When streaming is initiated
    Then data is decompressed during streaming

  Scenario: Stream from remote source
    Given a remote data URL
    When streaming is initiated
    Then data is fetched and streamed

  Scenario: Stream from local file
    Given a local file path
    When streaming is initiated
    Then data is read and streamed

  Scenario: Resume interrupted stream
    Given a partially streamed dataset
    When streaming resumes
    Then streaming continues from last position

  Scenario: Apply transformation during streaming
    Given a transformation function
    When data is streamed
    Then transformation is applied to each item

  Scenario: Filter data during streaming
    Given a filter condition
    When data is streamed
    Then only matching items are yielded

  Scenario: Monitor streaming progress
    Given progress monitoring is enabled
    When data is streamed
    Then progress metrics are reported

  Scenario: Handle stream errors
    Given an error occurs during streaming
    When the error is encountered
    Then the error is handled gracefully
