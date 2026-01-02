Feature: WikipediaProcessor
  This feature file describes the WikipediaProcessor callable
  from ipfs_datasets_py.wikipedia_x.index module.

  Background:
    Given a WikipediaProcessor instance

  Scenario: Initialize with default configuration
    When the processor is initialized without config
    Then config is WikipediaConfig with defaults
    And db is empty dictionary
    And logger is set

  Scenario: Initialize with custom configuration
    Given WikipediaConfig with cache_dir as /tmp/cache
    When the processor is initialized with config
    Then config cache_dir is /tmp/cache
    And db is empty dictionary

  Scenario: Load dataset with valid name
    Given dataset_name as laion/Wikipedia-X
    When load_dataset is called
    Then dataset is loaded successfully
    And dataset is stored in db with key laion/Wikipedia-X
    And logger logs success message

  Scenario: Load dataset with empty name
    Given dataset_name as empty string
    When load_dataset is called
    Then ValueError is raised with message dataset_name cannot be empty

  Scenario: Load dataset with kwargs
    Given dataset_name as laion/Wikipedia-X
    And kwargs with split as train
    When load_dataset is called with kwargs
    Then dataset is loaded with split train

  Scenario: Load dataset merges config with kwargs
    Given WikipediaConfig with cache_dir as /tmp/cache
    And processor is initialized with config
    And dataset_name as laion/Wikipedia-X
    And kwargs with trust_remote_code as True
    When load_dataset is called with kwargs
    Then dataset is loaded with cache_dir /tmp/cache
    And dataset is loaded with trust_remote_code True

  Scenario: Load dataset handles loading failure
    Given dataset_name as invalid/dataset
    When load_dataset is called
    Then RuntimeError is raised with message Failed to load dataset
    And logger logs error message

  Scenario: Process datasets with single string
    Given dataset_names as laion/Wikipedia-X
    When process_datasets is called
    Then results contain laion/Wikipedia-X
    And laion/Wikipedia-X is loaded successfully

  Scenario: Process datasets with list of names
    Given dataset_names as list with laion/Wikipedia-X, laion/Wikipedia-M3
    When process_datasets is called
    Then results contain laion/Wikipedia-X
    And results contain laion/Wikipedia-M3
    And both datasets are loaded successfully

  Scenario: Process datasets with None
    Given dataset_names as None
    When process_datasets is called
    Then ValueError is raised with message dataset_names cannot be None

  Scenario: Process datasets with empty list
    Given dataset_names as empty list
    When process_datasets is called
    Then ValueError is raised with message dataset_names cannot be empty

  Scenario: Process datasets with invalid type
    Given dataset_names as integer 123
    When process_datasets is called
    Then TypeError is raised with message dataset_names must be a string or list

  Scenario: Process datasets continues on failure
    Given dataset_names as list with valid/dataset, invalid/dataset
    When process_datasets is called
    Then results contain valid/dataset
    And results do not contain invalid/dataset
    And logger logs error for invalid/dataset

  Scenario: Get dataset info for loaded dataset
    Given dataset_name as laion/Wikipedia-X
    And dataset is loaded
    When get_dataset_info is called
    Then info contains name as laion/Wikipedia-X
    And info contains features
    And info contains num_rows
    And info contains splits

  Scenario: Get dataset info for non-loaded dataset
    Given dataset_name as not/loaded
    When get_dataset_info is called
    Then result is None

  Scenario: Get dataset info handles errors
    Given dataset_name as laion/Wikipedia-X
    And dataset is loaded with error prone data
    When get_dataset_info is called
    Then info contains name as laion/Wikipedia-X
    And info contains error field

  Scenario: Clear cache
    Given 2 datasets are loaded
    When clear_cache is called
    Then db is empty
    And logger logs cache cleared

  Scenario: Get loaded datasets property
    Given 3 datasets are loaded
    When loaded_datasets property is accessed
    Then result is list with 3 dataset names
