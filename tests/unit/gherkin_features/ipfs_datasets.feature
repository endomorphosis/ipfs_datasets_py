Feature: IPFS Datasets Core
  Core IPFS dataset management functionality

  Scenario: Initialize IPFS dataset
    Given dataset configuration
    When IPFS dataset is initialized
    Then the dataset is ready for operations

  Scenario: Pin dataset to IPFS
    Given a dataset
    When pinning is requested
    Then the dataset is pinned to IPFS

  Scenario: Retrieve dataset from IPFS
    Given a dataset CID
    When retrieval is requested
    Then the dataset is fetched from IPFS

  Scenario: Add file to IPFS
    Given a file path
    When file addition is requested
    Then the file is added to IPFS
    And a CID is returned

  Scenario: List pinned datasets
    Given pinned datasets exist
    When listing is requested
    Then all pinned datasets are returned

  Scenario: Unpin dataset from IPFS
    Given a pinned dataset
    When unpinning is requested
    Then the dataset is unpinned

  Scenario: Get dataset metadata
    Given a dataset CID
    When metadata retrieval is requested
    Then dataset metadata is returned

  Scenario: Verify dataset integrity
    Given a dataset CID
    When integrity verification is performed
    Then the dataset integrity is confirmed

  Scenario: Export dataset to local storage
    Given a dataset from IPFS
    When local export is requested
    Then the dataset is saved locally
