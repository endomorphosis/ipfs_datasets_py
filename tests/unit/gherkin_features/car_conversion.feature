Feature: CAR File Conversion
  Data format conversion to and from Content Addressed aRchive files

  Scenario: Export Arrow table to CAR file
    Given a valid Arrow table
    When the table is exported to a CAR file
    Then a CAR file is created at the specified path
    And the root CID is returned

  Scenario: Export table with hash columns
    Given a valid Arrow table
    And specific columns are designated for hashing
    When the table is exported to a CAR file
    Then the table is content-addressed using the specified columns

  Scenario: Import Arrow table from CAR file
    Given a valid CAR file exists
    When the CAR file is imported
    Then an Arrow table is reconstructed

  Scenario: Handle missing Arrow dependency
    Given Arrow is not installed
    When a table export is attempted
    Then a mock CAR file is created

  Scenario: Handle missing IPLD CAR dependency
    Given IPLD CAR library is not installed
    When a CAR export is attempted
    Then a mock CAR file is created

  Scenario: Serialize table to IPLD format
    Given a valid Arrow table
    When the table is serialized
    Then IPLD blocks are created
    And a root CID is generated

  Scenario: Export multiple CIDs to CAR archive
    Given multiple IPLD CIDs exist
    When the CIDs are exported to a CAR file
    Then a single CAR archive contains all blocks
