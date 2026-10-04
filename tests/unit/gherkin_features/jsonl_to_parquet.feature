Feature: JSONL to Parquet Conversion
  Convert JSONL data files to Parquet format

  Scenario: Convert JSONL file to Parquet
    Given a valid JSONL file
    When conversion to Parquet is requested
    Then a Parquet file is created

  Scenario: Convert with schema inference
    Given a JSONL file without schema
    When conversion is performed
    Then the schema is inferred from data

  Scenario: Convert with explicit schema
    Given a JSONL file and a schema definition
    When conversion is performed
    Then the Parquet file uses the provided schema

  Scenario: Handle nested JSON structures
    Given a JSONL file with nested objects
    When conversion is performed
    Then nested structures are preserved in Parquet

  Scenario: Convert large JSONL file
    Given a large JSONL file
    When conversion is performed in batches
    Then the file is converted without memory overflow

  Scenario: Validate Parquet output
    Given a converted Parquet file
    When validation is performed
    Then the data matches source JSONL

  Scenario: Handle conversion errors
    Given a JSONL file with invalid rows
    When conversion is attempted
    Then errors are logged
    And valid rows are converted

  Scenario: Compress Parquet output
    Given a JSONL file and compression option
    When conversion is performed
    Then the Parquet file is compressed

  Scenario: Convert with column selection
    Given a JSONL file and selected columns
    When conversion is performed
    Then only selected columns are included
