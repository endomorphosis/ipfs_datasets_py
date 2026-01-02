Feature: WikipediaConfig
  This feature file describes the WikipediaConfig callable
  from ipfs_datasets_py.wikipedia_x.index module.

  Scenario: Initialize with default values
    When WikipediaConfig is created without parameters
    Then cache_dir is None
    And trust_remote_code is False
    And revision is None
    And use_auth_token is False

  Scenario: Initialize with cache_dir
    When WikipediaConfig is created with cache_dir as /tmp/cache
    Then cache_dir is /tmp/cache
    And trust_remote_code is False
    And revision is None
    And use_auth_token is False

  Scenario: Initialize with trust_remote_code
    When WikipediaConfig is created with trust_remote_code as True
    Then cache_dir is None
    And trust_remote_code is True
    And revision is None
    And use_auth_token is False

  Scenario: Initialize with revision
    When WikipediaConfig is created with revision as v1.0.0
    Then cache_dir is None
    And trust_remote_code is False
    And revision is v1.0.0
    And use_auth_token is False

  Scenario: Initialize with use_auth_token as boolean
    When WikipediaConfig is created with use_auth_token as True
    Then cache_dir is None
    And trust_remote_code is False
    And revision is None
    And use_auth_token is True

  Scenario: Initialize with use_auth_token as string
    When WikipediaConfig is created with use_auth_token as hf_token_123
    Then cache_dir is None
    And trust_remote_code is False
    And revision is None
    And use_auth_token is hf_token_123

  Scenario: Initialize with all parameters
    When WikipediaConfig is created with all parameters
    Then cache_dir is /tmp/cache
    And trust_remote_code is True
    And revision is v1.0.0
    And use_auth_token is hf_token_123
