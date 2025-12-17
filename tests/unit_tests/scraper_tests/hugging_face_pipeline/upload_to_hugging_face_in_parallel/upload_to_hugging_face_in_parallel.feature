Feature: Upload files to HuggingFace in parallel

  Background:
    Given a HuggingFace repository exists with ID "test-repo"
    And the user has a valid access token
    And the rate limiter allows 300 requests per hour

  Rule: Files upload successfully when API is available

    Scenario: Upload all files
      Given an output directory at "/data/output" contains 10 parquet files and target directory name is "municipal_laws"
      When upload_to_hugging_face_in_parallel is called
      Then the return value contains "uploaded": 10, "failed": 0, "retried": 0

  Rule: File pattern filters determine which files upload

    Scenario: Upload only matching files
      Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then 5 files are uploaded

    Scenario: Skip non-matching files
      Given an output directory at "/data/output" contains 5 parquet files and 3 json files with file_path_ending ".parquet" and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then 3 files are not uploaded

  Rule: Rate limiter controls upload timing

    Background:
      Given the rate limiter has 5 tokens

    Scenario: Wait when tokens exhausted
      Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then the upload waits for tokens before proceeding

    Scenario: Complete upload after tokens replenish
      Given an output directory at "/data/output" contains 20 files with max_concurrency 10 and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then 20 files are uploaded

  Rule: Failed uploads retry until success or max retries

    Background:
      Given an output directory at "/data/output" contains 3 files and target directory name "laws"

    Scenario: Retry and succeed
      Given the HuggingFace API returns error on first attempt
      And the API succeeds on second attempt
      When upload_to_hugging_face_in_parallel is called
      Then the return value contains "uploaded": 3, "failed": 0, "retried": 1

    Scenario: Fail after max retries
      Given the HuggingFace API returns error on all attempts
      And max_retries is 3
      When upload_to_hugging_face_in_parallel is called
      Then the return value contains "uploaded": 0, "failed": 3, "retried": 3

  Rule: Max concurrency limits parallel uploads

    Scenario: Enforce concurrency limit
      Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then no more than 5 uploads run at once

    Scenario: Complete all uploads
      Given an output directory at "/data/output" contains 100 files with max_concurrency 5 and target directory name "laws"
      When upload_to_hugging_face_in_parallel is called
      Then 100 files are uploaded

  Rule: Upload mode determines granularity

    Background:
      Given an output directory at "/data/output" contains 8 files in 2 folders and target directory name "laws"

    Scenario: Upload files individually
      Given upload_piecemeal is True
      When upload_to_hugging_face_in_parallel is called
      Then 8 files are uploaded individually

    Scenario: Upload folders
      Given upload_piecemeal is False
      When upload_to_hugging_face_in_parallel is called
      Then 2 folders are uploaded

  Rule: Return value provides upload statistics

    Scenario: Return statistics for mixed results
      Given an output directory at "/data/output" contains 15 files and target directory name "laws"
      And 12 files upload on first attempt
      And 2 files upload on second attempt
      And 1 file fails after retries
      When upload_to_hugging_face_in_parallel is called
      Then the return value contains "uploaded": 14, "failed": 1, "retried": 2