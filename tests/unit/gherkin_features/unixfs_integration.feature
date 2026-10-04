Feature: UnixFS Integration
  Integration with IPFS UnixFS file system

  Scenario: Create UnixFS file
    Given file content
    When UnixFS file creation is requested
    Then a UnixFS file object is created

  Scenario: Create UnixFS directory
    Given directory structure
    When UnixFS directory creation is requested
    Then a UnixFS directory object is created

  Scenario: Add file to UnixFS directory
    Given a UnixFS directory and file
    When file addition is requested
    Then the file is added to the directory

  Scenario: Read UnixFS file
    Given a UnixFS file CID
    When file reading is requested
    Then file content is returned

  Scenario: List UnixFS directory contents
    Given a UnixFS directory CID
    When directory listing is requested
    Then directory contents are returned

  Scenario: Remove file from UnixFS directory
    Given a UnixFS directory and file name
    When file removal is requested
    Then the file is removed from directory

  Scenario: Get UnixFS file metadata
    Given a UnixFS file CID
    When metadata retrieval is requested
    Then file metadata is returned

  Scenario: Stream large UnixFS file
    Given a large UnixFS file
    When streaming is requested
    Then file content is streamed in chunks
