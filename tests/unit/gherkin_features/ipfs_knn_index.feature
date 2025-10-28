Feature: IPFS KNN Index
  K-nearest neighbors search on IPFS

  Scenario: Build KNN index
    Given a set of vectors
    When KNN index construction is requested
    Then an index is built

  Scenario: Add vectors to index
    Given an existing KNN index
    And new vectors
    When vectors are added
    Then the index is updated

  Scenario: Search for nearest neighbors
    Given a KNN index and query vector
    When nearest neighbor search is performed
    Then the k nearest vectors are returned

  Scenario: Search with distance threshold
    Given a KNN index and distance threshold
    When search is performed
    Then only vectors within threshold are returned

  Scenario: Store index on IPFS
    Given a built KNN index
    When IPFS storage is requested
    Then the index is stored on IPFS
    And a CID is returned

  Scenario: Load index from IPFS
    Given an index CID
    When index loading is requested
    Then the index is retrieved from IPFS

  Scenario: Update index incrementally
    Given an existing index
    And new data points
    When incremental update is performed
    Then the index is updated without full rebuild

  Scenario: Remove vectors from index
    Given an index with vectors
    When vector removal is requested
    Then specified vectors are removed from index
