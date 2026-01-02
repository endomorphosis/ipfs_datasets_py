Feature: test_ipfs_datasets_py
  This feature file describes the test_ipfs_datasets_py callable
  from ipfs_datasets_py.wikipedia_x.index module.

  Background:
    Given a test_ipfs_datasets_py instance

  Scenario: Initialize with processor backend
    When the test class is initialized
    Then processor is WikipediaProcessor instance
    And db is reference to processor db

  Scenario: Load dataset using compatibility method
    Given dataset_name as laion/Wikipedia-X
    When load_dataset is called
    Then processor load_dataset is called with dataset_name
    And dataset is loaded successfully
    And dataset is stored in db

  Scenario: Test method with single dataset
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then processor process_datasets is called
    And result contains laion/Wikipedia-X

  Scenario: Test method with multiple datasets
    Given datasets_list as list with laion/Wikipedia-X, laion/Wikipedia-M3
    When test is called with datasets_list
    Then processor process_datasets is called
    And result contains laion/Wikipedia-X
    And result contains laion/Wikipedia-M3

  Scenario: Test method forwards to process_datasets
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then process_datasets method is invoked
    And compatibility is maintained with old tests
