Feature: Parquet to CAR Conversion
  Convert Parquet files to IPFS CAR format

  Scenario: Convert Parquet file to CAR
    Given a Parquet file
    When CAR conversion is requested
    Then a CAR file is created

  Scenario: Convert with content addressing
    Given a Parquet file
    When conversion with content addressing is performed
    Then each row is content-addressed

  Scenario: Preserve Parquet schema in CAR
    Given a Parquet file with schema
    When conversion is performed
    Then the schema is preserved in CAR metadata

  Scenario: Handle large Parquet files
    Given a large Parquet file
    When conversion is performed in chunks
    Then the file is converted without memory overflow

  Scenario: Generate CID for Parquet data
    Given Parquet data
    When CID generation is requested
    Then a root CID is returned

  Scenario: Convert CAR back to Parquet
    Given a CAR file from Parquet
    When reverse conversion is performed
    Then the original Parquet data is reconstructed

  Scenario: Verify data integrity after conversion
    Given a converted CAR file
    When integrity check is performed
    Then the data matches the original Parquet
