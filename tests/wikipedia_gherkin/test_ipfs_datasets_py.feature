Feature: test_ipfs_datasets_py
  This feature file describes the test_ipfs_datasets_py callable
  from ipfs_datasets_py.wikipedia_x.index module.

  Background:
    Given a test_ipfs_datasets_py instance

  Scenario: Initialize with processor backend processor is WikipediaProcessor instance
    When the test class is initialized
    Then processor is WikipediaProcessor instance

  Scenario: Initialize with processor backend db is reference to processor db
    When the test class is initialized
    Then db is reference to processor db


  Scenario: Load dataset using compatibility method processor load_dataset is called with dataset_name
    Given dataset_name as laion/Wikipedia-X
    When load_dataset is called
    Then processor load_dataset is called with dataset_name

  Scenario: Load dataset using compatibility method dataset is loaded successfully
    Given dataset_name as laion/Wikipedia-X
    When load_dataset is called
    Then dataset is loaded successfully

  Scenario: Load dataset using compatibility method dataset is stored in db
    Given dataset_name as laion/Wikipedia-X
    When load_dataset is called
    Then dataset is stored in db


  Scenario: Test method with single dataset processor process_datasets is called
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then processor process_datasets is called

  Scenario: Test method with single dataset result contains laion/Wikipedia-X
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then result contains laion/Wikipedia-X


  Scenario: Test method with multiple datasets processor process_datasets is called
    Given datasets_list as list with laion/Wikipedia-X, laion/Wikipedia-M3
    When test is called with datasets_list
    Then processor process_datasets is called

  Scenario: Test method with multiple datasets result contains laion/Wikipedia-X
    Given datasets_list as list with laion/Wikipedia-X, laion/Wikipedia-M3
    When test is called with datasets_list
    Then result contains laion/Wikipedia-X

  Scenario: Test method with multiple datasets result contains laion/Wikipedia-M3
    Given datasets_list as list with laion/Wikipedia-X, laion/Wikipedia-M3
    When test is called with datasets_list
    Then result contains laion/Wikipedia-M3


  Scenario: Test method forwards to process_datasets process_datasets method is invoked
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then process_datasets method is invoked

  Scenario: Test method forwards to process_datasets compatibility is maintained with old tests
    Given datasets_list as laion/Wikipedia-X
    When test is called with datasets_list
    Then compatibility is maintained with old tests

