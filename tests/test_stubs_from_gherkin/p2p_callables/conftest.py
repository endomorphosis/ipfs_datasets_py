"""
Pytest fixtures for p2p callables tests.

This module provides fixtures for testing p2p workflow, monitoring, and cache functionality.
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock
from typing import Dict, Any, List

# Import FixtureError from parent conftest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import FixtureError


# ============================================================================
# MerkleClock Fixtures
# ============================================================================

@pytest.fixture
def peer_id_peer1():
    """
    Fixture: peer_id "peer1"
    
    Provides a peer ID string "peer1" for MerkleClock initialization.
    """
    try:
        peer_id = "peer1"
        if not isinstance(peer_id, str):
            raise FixtureError(f'Failed to create fixture peer_id_peer1: peer_id must be string, got {type(peer_id)}') from None
        if not peer_id:
            raise FixtureError('Failed to create fixture peer_id_peer1: peer_id cannot be empty') from None
        return peer_id
    except Exception as e:
        raise FixtureError(f'Failed to create fixture peer_id_peer1: {e}') from e


@pytest.fixture
def peer_id_peer2():
    """
    Fixture: peer_id "peer2"
    
    Provides a peer ID string "peer2" for MerkleClock initialization.
    """
    try:
        peer_id = "peer2"
        if not isinstance(peer_id, str):
            raise FixtureError(f'Failed to create fixture peer_id_peer2: peer_id must be string, got {type(peer_id)}') from None
        if not peer_id:
            raise FixtureError('Failed to create fixture peer_id_peer2: peer_id cannot be empty') from None
        return peer_id
    except Exception as e:
        raise FixtureError(f'Failed to create fixture peer_id_peer2: {e}') from e


@pytest.fixture
def merkle_clock_peer1():
    """
    Fixture: MerkleClock("peer1")
    
    Creates a MerkleClock instance with peer_id "peer1" and counter starting at 0.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import MerkleClock
        
        clock = MerkleClock(peer_id="peer1")
        
        # Verify the clock was created correctly
        if not hasattr(clock, 'peer_id'):
            raise FixtureError('Failed to create fixture merkle_clock_peer1: MerkleClock missing peer_id attribute') from None
        if not hasattr(clock, 'counter'):
            raise FixtureError('Failed to create fixture merkle_clock_peer1: MerkleClock missing counter attribute') from None
        if clock.peer_id != "peer1":
            raise FixtureError(f'Failed to create fixture merkle_clock_peer1: expected peer_id "peer1", got "{clock.peer_id}"') from None
        if clock.counter != 0:
            raise FixtureError(f'Failed to create fixture merkle_clock_peer1: expected counter 0, got {clock.counter}') from None
        
        return clock
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture merkle_clock_peer1: {e}') from e


@pytest.fixture
def merkle_clock_peer2():
    """
    Fixture: MerkleClock("peer2")
    
    Creates a MerkleClock instance with peer_id "peer2" and counter starting at 0.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import MerkleClock
        
        clock = MerkleClock(peer_id="peer2")
        
        # Verify the clock was created correctly
        if not hasattr(clock, 'peer_id'):
            raise FixtureError('Failed to create fixture merkle_clock_peer2: MerkleClock missing peer_id attribute') from None
        if not hasattr(clock, 'counter'):
            raise FixtureError('Failed to create fixture merkle_clock_peer2: MerkleClock missing counter attribute') from None
        if clock.peer_id != "peer2":
            raise FixtureError(f'Failed to create fixture merkle_clock_peer2: expected peer_id "peer2", got "{clock.peer_id}"') from None
        if clock.counter != 0:
            raise FixtureError(f'Failed to create fixture merkle_clock_peer2: expected counter 0, got {clock.counter}') from None
        
        return clock
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture merkle_clock_peer2: {e}') from e


@pytest.fixture
def merkle_clock_with_counter_2():
    """
    Fixture: MerkleClock("peer1") with counter=2
    
    Creates a MerkleClock instance with peer_id "peer1" and manually sets counter to 2.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import MerkleClock
        
        clock = MerkleClock(peer_id="peer1", counter=2)
        
        # Verify the clock state
        if clock.counter != 2:
            raise FixtureError(f'Failed to create fixture merkle_clock_with_counter_2: expected counter 2, got {clock.counter}') from None
        
        return clock
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture merkle_clock_with_counter_2: {e}') from e


@pytest.fixture
def merkle_clock_with_counter_1():
    """
    Fixture: MerkleClock("peer2") with counter=1
    
    Creates a MerkleClock instance with peer_id "peer2" and manually sets counter to 1.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import MerkleClock
        
        clock = MerkleClock(peer_id="peer2", counter=1)
        
        # Verify the clock state
        if clock.counter != 1:
            raise FixtureError(f'Failed to create fixture merkle_clock_with_counter_1: expected counter 1, got {clock.counter}') from None
        
        return clock
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture merkle_clock_with_counter_1: {e}') from e


# ============================================================================
# Workflow Scheduler Fixtures
# ============================================================================

@pytest.fixture
def peer_ids_list():
    """
    Fixture: peer_ids ["peer1", "peer2", "peer3"]
    
    Provides a list of peer IDs for P2P workflow scheduler initialization.
    """
    try:
        peers = ["peer1", "peer2", "peer3"]
        
        # Verify it's a list with 3 peers
        if not isinstance(peers, list):
            raise FixtureError(f'Failed to create fixture peer_ids_list: expected list, got {type(peers)}') from None
        if len(peers) != 3:
            raise FixtureError(f'Failed to create fixture peer_ids_list: expected 3 peers, got {len(peers)}') from None
        
        return peers
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture peer_ids_list: {e}') from e


@pytest.fixture
def p2p_workflow_scheduler():
    """
    Fixture: P2PWorkflowScheduler("peer1", peers=["peer1", "peer2", "peer3"])
    
    Creates a P2PWorkflowScheduler instance with peer1 as the current peer.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import P2PWorkflowScheduler
        
        peers = ["peer1", "peer2", "peer3"]
        scheduler = P2PWorkflowScheduler(peer_id="peer1", peers=peers)
        
        # Verify scheduler was created correctly
        if not hasattr(scheduler, 'peer_id'):
            raise FixtureError('Failed to create fixture p2p_workflow_scheduler: missing peer_id attribute') from None
        if scheduler.peer_id != "peer1":
            raise FixtureError(f'Failed to create fixture p2p_workflow_scheduler: expected peer_id "peer1", got "{scheduler.peer_id}"') from None
        
        return scheduler
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture p2p_workflow_scheduler: {e}') from e


@pytest.fixture
def workflow_definition_p2p_eligible():
    """
    Fixture: WorkflowDefinition(workflow_id="wf1", tags=[WorkflowTag.P2P_ELIGIBLE], priority=2.0)
    
    Creates a workflow definition that is eligible for P2P execution.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import WorkflowDefinition, WorkflowTag
        
        workflow = WorkflowDefinition(
            workflow_id="wf1",
            tags=[WorkflowTag.P2P_ELIGIBLE],
            priority=2.0
        )
        
        # Verify workflow properties
        if workflow.workflow_id != "wf1":
            raise FixtureError(f'Failed to create fixture workflow_definition_p2p_eligible: expected workflow_id "wf1", got "{workflow.workflow_id}"') from None
        if WorkflowTag.P2P_ELIGIBLE not in workflow.tags:
            raise FixtureError('Failed to create fixture workflow_definition_p2p_eligible: P2P_ELIGIBLE tag not in workflow tags') from None
        if workflow.priority != 2.0:
            raise FixtureError(f'Failed to create fixture workflow_definition_p2p_eligible: expected priority 2.0, got {workflow.priority}') from None
        
        return workflow
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture workflow_definition_p2p_eligible: {e}') from e


@pytest.fixture
def workflow_definition_p2p_only():
    """
    Fixture: WorkflowDefinition(workflow_id="wf2", tags=[WorkflowTag.P2P_ONLY], priority=1.0)
    
    Creates a workflow definition that must use P2P execution only.
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import WorkflowDefinition, WorkflowTag
        
        workflow = WorkflowDefinition(
            workflow_id="wf2",
            tags=[WorkflowTag.P2P_ONLY],
            priority=1.0
        )
        
        # Verify workflow properties
        if workflow.workflow_id != "wf2":
            raise FixtureError(f'Failed to create fixture workflow_definition_p2p_only: expected workflow_id "wf2", got "{workflow.workflow_id}"') from None
        if WorkflowTag.P2P_ONLY not in workflow.tags:
            raise FixtureError('Failed to create fixture workflow_definition_p2p_only: P2P_ONLY tag not in workflow tags') from None
        
        return workflow
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture workflow_definition_p2p_only: {e}') from e


@pytest.fixture
def workflow_definition_unit_test():
    """
    Fixture: WorkflowDefinition(tags=[WorkflowTag.UNIT_TEST])
    
    Creates a workflow definition for unit tests (not P2P eligible).
    """
    try:
        from ipfs_datasets_py.p2p_workflow_scheduler import WorkflowDefinition, WorkflowTag
        
        workflow = WorkflowDefinition(
            workflow_id="wf_unit_test",
            tags=[WorkflowTag.UNIT_TEST],
            priority=1.0
        )
        
        # Verify workflow properties
        if WorkflowTag.UNIT_TEST not in workflow.tags:
            raise FixtureError('Failed to create fixture workflow_definition_unit_test: UNIT_TEST tag not in workflow tags') from None
        
        return workflow
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture workflow_definition_unit_test: {e}') from e


# ============================================================================
# Cache and Monitoring Fixtures
# ============================================================================

@pytest.fixture
def mock_cache_with_stats():
    """
    Fixture: cache instance with stats
    
    Creates a mock cache object with statistics for testing print_stats function.
    """
    try:
        cache = Mock()
        cache.size = 100
        cache.max_size = 1000
        cache.total_requests = 500
        cache.hits = 400
        cache.misses = 100
        cache.p2p_enabled = True
        cache.connected_peers = 3
        cache._cipher = Mock()  # Mock cipher to indicate encryption is enabled
        cache.key_derivation = "PBKDF2-HMAC-SHA256"
        cache.api_calls_prevented = 300
        cache.time_saved_seconds = 150
        cache.rate_limit_hits_prevented = 50
        
        # Verify cache has required attributes
        required_attrs = ['size', 'max_size', 'total_requests', 'hits', 'misses']
        for attr in required_attrs:
            if not hasattr(cache, attr):
                raise FixtureError(f'Failed to create fixture mock_cache_with_stats: missing required attribute {attr}') from None
        
        return cache
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_cache_with_stats: {e}') from e


@pytest.fixture
def mock_cache_with_p2p():
    """
    Fixture: cache with P2P enabled
    
    Creates a mock cache object with P2P networking enabled.
    """
    try:
        cache = Mock()
        cache.p2p_enabled = True
        cache.connected_peers = 3
        cache._peer_registry = Mock()
        
        # Verify P2P is enabled
        if not cache.p2p_enabled:
            raise FixtureError('Failed to create fixture mock_cache_with_p2p: p2p_enabled is not True') from None
        
        return cache
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_cache_with_p2p: {e}') from e


@pytest.fixture
def mock_cache_with_encryption():
    """
    Fixture: cache with encryption cipher
    
    Creates a mock cache object with encryption enabled.
    """
    try:
        cache = Mock()
        cache._cipher = Mock()  # Non-None cipher indicates encryption is enabled
        cache.key_derivation = "PBKDF2-HMAC-SHA256"
        
        # Verify cipher exists
        if cache._cipher is None:
            raise FixtureError('Failed to create fixture mock_cache_with_encryption: cipher is None') from None
        
        return cache
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_cache_with_encryption: {e}') from e


@pytest.fixture
def temp_cache_dir():
    """
    Fixture: Temporary directory for cache operations
    
    Creates a temporary directory for cache testing and cleans it up after test.
    """
    try:
        cache_dir = tempfile.mkdtemp(prefix="p2p_cache_test_")
        cache_path = Path(cache_dir)
        
        # Verify directory was created
        if not cache_path.exists():
            raise FixtureError(f'Failed to create fixture temp_cache_dir: directory {cache_dir} does not exist after creation') from None
        if not cache_path.is_dir():
            raise FixtureError(f'Failed to create fixture temp_cache_dir: {cache_dir} is not a directory') from None
        
        yield cache_path
        
        # Cleanup
        try:
            shutil.rmtree(cache_dir)
            # Verify cleanup
            if cache_path.exists():
                raise FixtureError(f'Failed to cleanup fixture temp_cache_dir: directory {cache_dir} still exists after cleanup') from None
        except Exception as cleanup_error:
            raise FixtureError(f'Failed to cleanup fixture temp_cache_dir: {cleanup_error}') from cleanup_error
            
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture temp_cache_dir: {e}') from e


@pytest.fixture
def environment_variables():
    """
    Fixture: Environment variables set
    
    Provides mock environment variables for P2P cache initialization.
    """
    try:
        env_vars = {
            "CACHE_DIR": "/tmp/cache",
            "GITHUB_REPO": "user/repo",
            "CACHE_SIZE": "1000",
            "ENABLE_P2P": "true",
            "ENABLE_PEER_DISCOVERY": "true",
            "GITHUB_TOKEN": "test_token_12345"
        }
        
        # Verify all required variables are present
        required_vars = ["CACHE_DIR", "GITHUB_REPO", "CACHE_SIZE", "ENABLE_P2P"]
        for var in required_vars:
            if var not in env_vars:
                raise FixtureError(f'Failed to create fixture environment_variables: missing required variable {var}') from None
        
        # Temporarily set environment variables
        original_env = {}
        for key, value in env_vars.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value
        
        yield env_vars
        
        # Restore original environment
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
                
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture environment_variables: {e}') from e


@pytest.fixture
def mock_test_function_success():
    """
    Fixture: test function that returns True
    
    Creates a mock test function that always returns True for testing check() function.
    """
    try:
        def test_fn():
            return True
        
        # Verify function is callable
        if not callable(test_fn):
            raise FixtureError('Failed to create fixture mock_test_function_success: test_fn is not callable') from None
        
        # Verify function returns True
        result = test_fn()
        if result is not True:
            raise FixtureError(f'Failed to create fixture mock_test_function_success: expected True, got {result}') from None
        
        return test_fn
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_test_function_success: {e}') from e


@pytest.fixture
def mock_test_function_failure():
    """
    Fixture: test function that returns False
    
    Creates a mock test function that always returns False for testing check() function.
    """
    try:
        def test_fn():
            return False
        
        # Verify function is callable
        if not callable(test_fn):
            raise FixtureError('Failed to create fixture mock_test_function_failure: test_fn is not callable') from None
        
        # Verify function returns False
        result = test_fn()
        if result is not False:
            raise FixtureError(f'Failed to create fixture mock_test_function_failure: expected False, got {result}') from None
        
        return test_fn
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_test_function_failure: {e}') from e


@pytest.fixture
def mock_test_function_exception():
    """
    Fixture: test function that raises exception
    
    Creates a mock test function that raises ValueError for testing check() error handling.
    """
    try:
        def test_fn():
            raise ValueError("test error")
        
        # Verify function is callable
        if not callable(test_fn):
            raise FixtureError('Failed to create fixture mock_test_function_exception: test_fn is not callable') from None
        
        # Verify function raises exception
        try:
            test_fn()
            raise FixtureError('Failed to create fixture mock_test_function_exception: test_fn did not raise exception') from None
        except ValueError as e:
            if str(e) != "test error":
                raise FixtureError(f'Failed to create fixture mock_test_function_exception: expected "test error", got "{str(e)}"') from None
        
        return test_fn
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture mock_test_function_exception: {e}') from e


# ============================================================================
# Additional utility fixtures
# ============================================================================

@pytest.fixture
def captured_output(capsys):
    """
    Fixture: Provides captured output utility
    
    Returns a function that can be called to get captured stdout/stderr.
    """
    try:
        def get_output():
            captured = capsys.readouterr()
            return captured.out + captured.err
        
        return get_output
    except Exception as e:
        raise FixtureError(f'Failed to create fixture captured_output: {e}') from e
