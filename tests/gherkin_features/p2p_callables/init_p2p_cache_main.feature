Feature: main function from scripts/ci/init_p2p_cache.py
  This function initializes and tests P2P cache

  Scenario: Import ipfs_datasets_py.cache succeeds
    When from ipfs_datasets_py.cache import GitHubAPICache
    Then ImportError not raised

  Scenario: Import p2p_peer_registry succeeds
    When from ipfs_datasets_py.p2p_peer_registry import PeerRegistry
    Then ImportError not raised

  Scenario: Read CACHE_DIR environment variable
    Given CACHE_DIR="/tmp/cache"
    When os.getenv("CACHE_DIR") is called
    Then result == "/tmp/cache"

  Scenario: Read GITHUB_REPO environment variable
    Given GITHUB_REPO="user/repo"
    When os.getenv("GITHUB_REPO") is called
    Then result == "user/repo"

  Scenario: Read CACHE_SIZE environment variable
    Given CACHE_SIZE="1000"
    When int(os.getenv("CACHE_SIZE")) is called
    Then result == 1000

  Scenario: Read ENABLE_P2P environment variable as True
    Given ENABLE_P2P="true"
    When os.getenv("ENABLE_P2P").lower() == "true"
    Then result == True

  Scenario: Read ENABLE_PEER_DISCOVERY environment variable as True
    Given ENABLE_PEER_DISCOVERY="true"
    When os.getenv("ENABLE_PEER_DISCOVERY").lower() == "true"
    Then result == True

  Scenario: Create GitHubAPICache with enable_p2p True
    Given config with enable_p2p=True
    When GitHubAPICache(enable_p2p=True) is called
    Then cache instance created

  Scenario: Cache has _peer_registry attribute
    Given cache with P2P enabled
    When hasattr(cache, "_peer_registry") is checked
    Then result == True

  Scenario: Discover 5 peers returns list
    Given peer_registry with max_peers=5
    When peer_registry.discover_peers(max_peers=5) is called
    Then isinstance(result, list)

  Scenario: Discover peers returns count
    Given peer_registry with max_peers=5
    When peer_registry.discover_peers(max_peers=5) is called
    Then len(result) <= 5

  Scenario: Put test data succeeds
    Given cache instance
    When cache.put("test_key", {"data": "value"}) is called
    Then no exception raised

  Scenario: Get test data returns original
    Given cache with data at "test_key"
    When cache.get("test_key") is called
    Then result == {"data": "value"}

  Scenario: Get stats returns total_entries as integer
    Given cache with operations
    When cache.get_stats() is called
    Then isinstance(stats["total_entries"], int)

  Scenario: Get stats returns hits as integer
    Given cache with operations
    When cache.get_stats() is called
    Then isinstance(stats["hits"], int)

  Scenario: Get stats returns misses as integer
    Given cache with operations
    When cache.get_stats() is called
    Then isinstance(stats["misses"], int)

  Scenario: Get stats returns peer_hits as integer
    Given cache with P2P operations
    When cache.get_stats() is called
    Then isinstance(stats["peer_hits"], int)

  Scenario: Successful initialization returns exit code 0
    Given all initialization steps succeed
    When main() completes
    Then sys.exit(0) is called

  Scenario: Successful initialization outputs success message
    Given all initialization steps succeed
    When main() completes
    Then output contains "SUCCESS"

  Scenario: Import failure outputs warning
    Given import raises ImportError
    When main() is called
    Then output contains "WARNING"

  Scenario: Import failure returns exit code 0
    Given import raises ImportError
    When main() is called
    Then sys.exit(0) is called

  Scenario: Initialization exception outputs error
    Given cache initialization raises Exception
    When main() is called
    Then output contains "ERROR"

  Scenario: Initialization exception returns exit code 1
    Given cache initialization raises Exception
    When main() is called
    Then sys.exit(1) is called
