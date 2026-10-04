Feature: S3 Storage Kit
  Amazon S3 and compatible storage operations

  Scenario: Initialize S3 client
    Given S3 credentials and endpoint
    When the S3 client is initialized
    Then the client is ready for operations

  Scenario: Upload file to S3 bucket
    Given a file path and bucket name
    When file upload is requested
    Then the file is uploaded to S3

  Scenario: Download file from S3 bucket
    Given an S3 object key and bucket name
    When file download is requested
    Then the file is downloaded locally

  Scenario: List objects in bucket
    Given a bucket name
    When object listing is requested
    Then all objects in bucket are returned

  Scenario: Delete object from bucket
    Given an object key and bucket name
    When deletion is requested
    Then the object is removed from S3

  Scenario: Check object existence
    Given an object key and bucket name
    When existence check is performed
    Then the existence status is returned

  Scenario: Generate presigned URL
    Given an object key and expiration time
    When presigned URL generation is requested
    Then a temporary access URL is created

  Scenario: Set object metadata
    Given an object key and metadata
    When metadata is set
    Then the object metadata is updated

  Scenario: Copy object between buckets
    Given source and destination bucket details
    When copy operation is performed
    Then the object is copied to destination

  Scenario: Upload with multipart
    Given a large file
    When multipart upload is performed
    Then the file is uploaded in parts

  Scenario: Handle S3 errors
    Given an invalid S3 operation
    When the operation is attempted
    Then appropriate error is raised
