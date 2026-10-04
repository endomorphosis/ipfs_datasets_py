Feature: WikipediaConfig
  This feature file describes the WikipediaConfig callable
  from ipfs_datasets_py.wikipedia_x.index module.

  Scenario: Initialize with default values cache_dir is None
    When WikipediaConfig is created without parameters
    Then cache_dir is None

  Scenario: Initialize with default values trust_remote_code is False
    When WikipediaConfig is created without parameters
    Then trust_remote_code is False

  Scenario: Initialize with default values revision is None
    When WikipediaConfig is created without parameters
    Then revision is None

  Scenario: Initialize with default values use_auth_token is False
    When WikipediaConfig is created without parameters
    Then use_auth_token is False


  Scenario: Initialize with cache_dir cache_dir is /tmp/cache
    When WikipediaConfig is created with cache_dir as /tmp/cache
    Then cache_dir is /tmp/cache

  Scenario: Initialize with cache_dir trust_remote_code is False
    When WikipediaConfig is created with cache_dir as /tmp/cache
    Then trust_remote_code is False

  Scenario: Initialize with cache_dir revision is None
    When WikipediaConfig is created with cache_dir as /tmp/cache
    Then revision is None

  Scenario: Initialize with cache_dir use_auth_token is False
    When WikipediaConfig is created with cache_dir as /tmp/cache
    Then use_auth_token is False


  Scenario: Initialize with trust_remote_code cache_dir is None
    When WikipediaConfig is created with trust_remote_code as True
    Then cache_dir is None

  Scenario: Initialize with trust_remote_code trust_remote_code is True
    When WikipediaConfig is created with trust_remote_code as True
    Then trust_remote_code is True

  Scenario: Initialize with trust_remote_code revision is None
    When WikipediaConfig is created with trust_remote_code as True
    Then revision is None

  Scenario: Initialize with trust_remote_code use_auth_token is False
    When WikipediaConfig is created with trust_remote_code as True
    Then use_auth_token is False


  Scenario: Initialize with revision cache_dir is None
    When WikipediaConfig is created with revision as v1.0.0
    Then cache_dir is None

  Scenario: Initialize with revision trust_remote_code is False
    When WikipediaConfig is created with revision as v1.0.0
    Then trust_remote_code is False

  Scenario: Initialize with revision revision is v1.0.0
    When WikipediaConfig is created with revision as v1.0.0
    Then revision is v1.0.0

  Scenario: Initialize with revision use_auth_token is False
    When WikipediaConfig is created with revision as v1.0.0
    Then use_auth_token is False


  Scenario: Initialize with use_auth_token as boolean cache_dir is None
    When WikipediaConfig is created with use_auth_token as True
    Then cache_dir is None

  Scenario: Initialize with use_auth_token as boolean trust_remote_code is False
    When WikipediaConfig is created with use_auth_token as True
    Then trust_remote_code is False

  Scenario: Initialize with use_auth_token as boolean revision is None
    When WikipediaConfig is created with use_auth_token as True
    Then revision is None

  Scenario: Initialize with use_auth_token as boolean use_auth_token is True
    When WikipediaConfig is created with use_auth_token as True
    Then use_auth_token is True


  Scenario: Initialize with use_auth_token as string cache_dir is None
    When WikipediaConfig is created with use_auth_token as hf_token_123
    Then cache_dir is None

  Scenario: Initialize with use_auth_token as string trust_remote_code is False
    When WikipediaConfig is created with use_auth_token as hf_token_123
    Then trust_remote_code is False

  Scenario: Initialize with use_auth_token as string revision is None
    When WikipediaConfig is created with use_auth_token as hf_token_123
    Then revision is None

  Scenario: Initialize with use_auth_token as string use_auth_token is hf_token_123
    When WikipediaConfig is created with use_auth_token as hf_token_123
    Then use_auth_token is hf_token_123


  Scenario: Initialize with all parameters cache_dir is /tmp/cache
    When WikipediaConfig is created with all parameters
    Then cache_dir is /tmp/cache

  Scenario: Initialize with all parameters trust_remote_code is True
    When WikipediaConfig is created with all parameters
    Then trust_remote_code is True

  Scenario: Initialize with all parameters revision is v1.0.0
    When WikipediaConfig is created with all parameters
    Then revision is v1.0.0

  Scenario: Initialize with all parameters use_auth_token is hf_token_123
    When WikipediaConfig is created with all parameters
    Then use_auth_token is hf_token_123

