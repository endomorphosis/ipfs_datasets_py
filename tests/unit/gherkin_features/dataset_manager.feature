Feature: Dataset Management
  Dataset loading, saving, and lifecycle management

  Scenario: Get dataset by ID
    Given a dataset manager is initialized
    When a dataset is requested by ID
    Then the dataset is retrieved

  Scenario: Load dataset from HuggingFace Hub
    Given a dataset manager is initialized
    And a valid HuggingFace dataset ID is provided
    When the dataset is requested
    Then the dataset is loaded from HuggingFace Hub

  Scenario: Create mock dataset when loading fails
    Given a dataset manager is initialized
    And an invalid dataset ID is provided
    When the dataset is requested
    Then a mock dataset is created

  Scenario: Save dataset to manager
    Given a dataset manager is initialized
    And a valid dataset object
    When the dataset is saved with an ID
    Then the dataset is stored in the manager

  Scenario: Save dataset asynchronously to destination
    Given a managed dataset exists
    When the dataset is saved asynchronously to a destination
    Then the save operation completes
    And save metadata is returned

  Scenario: Save dataset synchronously to destination
    Given a managed dataset exists
    When the dataset is saved synchronously to a destination
    Then the save operation completes
    And save metadata is returned

  Scenario: Save dataset with custom format
    Given a managed dataset exists
    When the dataset is saved with a specified format
    Then the dataset is saved in the specified format

  Scenario: Retrieve existing dataset
    Given a dataset is already stored in the manager
    When the dataset is requested by its ID
    Then the stored dataset is returned
