"""
Pytest configuration and shared fixtures for UCAN callables tests.

This module provides common fixtures for testing UCANManager methods.
All fixtures follow the pattern:
- Implementation reflects the docstring
- Try-except with FixtureError for failures
- IO operations are verified
"""
import pytest
import os
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
import sys

# Import FixtureError from parent conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import FixtureError

# Import UCAN module
try:
    from ipfs_datasets_py.ucan import (
        UCANManager,
        UCANKeyPair,
        UCANCapability,
        UCANToken,
        CRYPTOGRAPHY_AVAILABLE,
        DEFAULT_UCAN_DIR
    )
    UCAN_MODULE_AVAILABLE = True
except ImportError as e:
    UCAN_MODULE_AVAILABLE = False
    IMPORT_ERROR = e


# =============================================================================
# Common Fixtures
# =============================================================================

@pytest.fixture
def the_ucanmanager_class_is_imported():
    """
    Given the UCANManager class is imported
    
    Returns the UCANManager class if available.
    Raises FixtureError if the module cannot be imported.
    """
    try:
        if not UCAN_MODULE_AVAILABLE:
            raise FixtureError(f'Failed to create fixture the_ucanmanager_class_is_imported: {IMPORT_ERROR}') from IMPORT_ERROR
        
        # Verify the class is actually available
        if not hasattr(UCANManager, 'get_instance'):
            raise AttributeError("UCANManager does not have get_instance method")
        
        return UCANManager
    except Exception as e:
        raise FixtureError(f'Failed to create fixture the_ucanmanager_class_is_imported: {e}') from e


@pytest.fixture
def a_ucanmanager_instance_is_initialized(the_ucanmanager_class_is_imported, tmp_path):
    """
    Given a UCANManager instance is initialized
    
    Returns an initialized UCANManager instance.
    Uses a temporary directory for UCAN storage to avoid conflicts.
    Raises FixtureError if initialization fails.
    """
    try:
        if not CRYPTOGRAPHY_AVAILABLE:
            raise FixtureError('Failed to create fixture a_ucanmanager_instance_is_initialized: cryptography module not available') from None
        
        # Use temporary directory for UCAN storage
        test_ucan_dir = tmp_path / "ucan"
        test_ucan_dir.mkdir(exist_ok=True)
        
        # Verify directory was created
        if not test_ucan_dir.exists():
            raise FixtureError(f'Failed to create fixture a_ucanmanager_instance_is_initialized: Could not create test directory {test_ucan_dir}') from None
        
        # Get and initialize the manager
        manager = the_ucanmanager_class_is_imported.get_instance()
        
        # Temporarily override the default directory
        original_dir = DEFAULT_UCAN_DIR
        import ipfs_datasets_py.ucan as ucan_module
        ucan_module.DEFAULT_UCAN_DIR = str(test_ucan_dir)
        
        success = manager.initialize()
        if not success:
            raise FixtureError('Failed to create fixture a_ucanmanager_instance_is_initialized: initialize() returned False') from None
        
        # Verify initialization
        if not manager.initialized:
            raise FixtureError('Failed to create fixture a_ucanmanager_instance_is_initialized: manager.initialized is False after initialize()') from None
        
        yield manager
        
        # Cleanup: restore original directory
        ucan_module.DEFAULT_UCAN_DIR = original_dir
        
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture a_ucanmanager_instance_is_initialized: {e}') from e


@pytest.fixture
def a_ucanmanager_instance_is_created_via_get_instance(the_ucanmanager_class_is_imported):
    """
    Given a UCANManager instance is created via get_instance()
    
    Returns a UCANManager instance (not initialized).
    Raises FixtureError if creation fails.
    """
    try:
        manager = the_ucanmanager_class_is_imported.get_instance()
        
        # Verify we got an instance
        if manager is None:
            raise FixtureError('Failed to create fixture a_ucanmanager_instance_is_created_via_get_instance: get_instance() returned None') from None
        
        if not isinstance(manager, the_ucanmanager_class_is_imported):
            raise FixtureError(f'Failed to create fixture a_ucanmanager_instance_is_created_via_get_instance: get_instance() returned {type(manager)} instead of UCANManager') from None
        
        return manager
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture a_ucanmanager_instance_is_created_via_get_instance: {e}') from e


@pytest.fixture
def the_cryptography_module_is_available():
    """
    Given the cryptography module is available
    
    Returns True if cryptography is available, otherwise raises FixtureError.
    """
    try:
        if not CRYPTOGRAPHY_AVAILABLE:
            raise FixtureError('Failed to create fixture the_cryptography_module_is_available: cryptography module is not installed') from None
        
        # Try to import key classes to verify
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        
        return True
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture the_cryptography_module_is_available: {e}') from e


@pytest.fixture
def the_default_ucan_directory_exists_at_ipfs_datasetsucan(tmp_path):
    """
    Given the default UCAN directory exists at ~/.ipfs_datasets/ucan
    
    Creates and returns the path to a temporary UCAN directory for testing.
    Raises FixtureError if directory cannot be created.
    """
    try:
        # Use temporary directory for testing
        test_dir = tmp_path / ".ipfs_datasets" / "ucan"
        test_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify directory was created
        if not test_dir.exists():
            raise FixtureError(f'Failed to create fixture the_default_ucan_directory_exists_at_ipfs_datasetsucan: Directory {test_dir} was not created') from None
        
        if not test_dir.is_dir():
            raise FixtureError(f'Failed to create fixture the_default_ucan_directory_exists_at_ipfs_datasetsucan: {test_dir} is not a directory') from None
        
        return test_dir
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture the_default_ucan_directory_exists_at_ipfs_datasetsucan: {e}') from e


# =============================================================================
# Keypair Fixtures
# =============================================================================

@pytest.fixture
def issuer_keypair_exists_with_diddidkeyalice_and_private_key(a_ucanmanager_instance_is_initialized):
    """
    Given issuer keypair exists with did="did:key:alice" and private key
    
    Creates and returns a keypair for Alice with both public and private keys.
    Raises FixtureError if keypair creation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate a keypair
        keypair = manager.generate_keypair()
        
        # Verify keypair has required attributes
        if not keypair.did:
            raise FixtureError('Failed to create fixture issuer_keypair_exists_with_diddidkeyalice_and_private_key: Keypair missing did') from None
        
        if not keypair.private_key_pem:
            raise FixtureError('Failed to create fixture issuer_keypair_exists_with_diddidkeyalice_and_private_key: Keypair missing private_key_pem') from None
        
        if not keypair.public_key_pem:
            raise FixtureError('Failed to create fixture issuer_keypair_exists_with_diddidkeyalice_and_private_key: Keypair missing public_key_pem') from None
        
        return keypair
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture issuer_keypair_exists_with_diddidkeyalice_and_private_key: {e}') from e


@pytest.fixture
def issuer_keypair_exists_with_diddidkeyalice(a_ucanmanager_instance_is_initialized):
    """
    Given issuer keypair exists with did="did:key:alice"
    
    Creates and returns a keypair for Alice.
    Raises FixtureError if keypair creation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate a keypair
        keypair = manager.generate_keypair()
        
        # Verify keypair has required attributes
        if not keypair.did:
            raise FixtureError('Failed to create fixture issuer_keypair_exists_with_diddidkeyalice: Keypair missing did') from None
        
        return keypair
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture issuer_keypair_exists_with_diddidkeyalice: {e}') from e


@pytest.fixture
def audience_keypair_exists_with_diddidkeybob(a_ucanmanager_instance_is_initialized):
    """
    Given audience keypair exists with did="did:key:bob"
    
    Creates and returns a keypair for Bob.
    Raises FixtureError if keypair creation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate a keypair
        keypair = manager.generate_keypair()
        
        # Verify keypair has required attributes
        if not keypair.did:
            raise FixtureError('Failed to create fixture audience_keypair_exists_with_diddidkeybob: Keypair missing did') from None
        
        return keypair
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture audience_keypair_exists_with_diddidkeybob: {e}') from e


@pytest.fixture
def a_valid_pemencoded_public_key_is_available(a_ucanmanager_instance_is_initialized):
    """
    Given a valid PEM-encoded public key is available
    
    Generates a keypair and returns the public key PEM.
    Raises FixtureError if generation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate a keypair to get a valid public key
        keypair = manager.generate_keypair()
        
        # Verify public key is in PEM format
        if not keypair.public_key_pem.startswith("-----BEGIN"):
            raise FixtureError('Failed to create fixture a_valid_pemencoded_public_key_is_available: Public key is not in PEM format') from None
        
        return keypair.public_key_pem
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture a_valid_pemencoded_public_key_is_available: {e}') from e


@pytest.fixture
def a_valid_pemencoded_private_key_is_available(a_ucanmanager_instance_is_initialized):
    """
    Given a valid PEM-encoded private key is available
    
    Generates a keypair and returns the private key PEM.
    Raises FixtureError if generation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate a keypair to get a valid private key
        keypair = manager.generate_keypair()
        
        # Verify private key is in PEM format
        if not keypair.private_key_pem.startswith("-----BEGIN"):
            raise FixtureError('Failed to create fixture a_valid_pemencoded_private_key_is_available: Private key is not in PEM format') from None
        
        return keypair.private_key_pem
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture a_valid_pemencoded_private_key_is_available: {e}') from e


# =============================================================================
# Capability Fixtures
# =============================================================================

@pytest.fixture
def a_ucancapability_with_resourcefiledatatxt_and_actionread():
    """
    Given a UCANCapability with resource="file://data.txt" and action="read"
    
    Creates and returns a UCANCapability instance.
    Raises FixtureError if creation fails.
    """
    try:
        if not UCAN_MODULE_AVAILABLE:
            raise FixtureError(f'Failed to create fixture a_ucancapability_with_resourcefiledatatxt_and_actionread: UCAN module not available') from IMPORT_ERROR
        
        capability = UCANCapability(
            resource="file://data.txt",
            action="read"
        )
        
        # Verify capability attributes
        if capability.resource != "file://data.txt":
            raise FixtureError(f'Failed to create fixture a_ucancapability_with_resourcefiledatatxt_and_actionread: Resource is {capability.resource}, expected file://data.txt') from None
        
        if capability.action != "read":
            raise FixtureError(f'Failed to create fixture a_ucancapability_with_resourcefiledatatxt_and_actionread: Action is {capability.action}, expected read') from None
        
        return capability
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture a_ucancapability_with_resourcefiledatatxt_and_actionread: {e}') from e


@pytest.fixture
def alice_has_capability_resourcekey123_actionencrypt(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice):
    """
    Given alice has capability resource="key-123" action="encrypt"
    
    Creates a token granting Alice the encrypt capability and returns the capability.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError


@pytest.fixture
def alice_has_capability_resourcekey123_actiondelegate(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice):
    """
    Given alice has capability resource="key-123" action="delegate"
    
    Creates a token granting Alice the delegate capability and returns the capability.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError


@pytest.fixture
def the_token_has_capability_resourcefilesecrettxt_actionread():
    """
    Given the token has capability resource="file://secret.txt" action="read"
    
    Creates and returns a UCANCapability instance.
    Raises FixtureError if creation fails.
    """
    try:
        if not UCAN_MODULE_AVAILABLE:
            raise FixtureError(f'Failed to create fixture the_token_has_capability_resourcefilesecrettxt_actionread: UCAN module not available') from IMPORT_ERROR
        
        capability = UCANCapability(
            resource="file://secret.txt",
            action="read"
        )
        
        # Verify capability attributes
        if capability.resource != "file://secret.txt":
            raise FixtureError(f'Failed to create fixture the_token_has_capability_resourcefilesecrettxt_actionread: Resource is {capability.resource}, expected file://secret.txt') from None
        
        if capability.action != "read":
            raise FixtureError(f'Failed to create fixture the_token_has_capability_resourcefilesecrettxt_actionread: Action is {capability.action}, expected read') from None
        
        return capability
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture the_token_has_capability_resourcefilesecrettxt_actionread: {e}') from e


# =============================================================================
# Token Fixtures
# =============================================================================

@pytest.fixture
def a_token_exists_with_audiencedidkeybob(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice_and_private_key, audience_keypair_exists_with_diddidkeybob):
    """
    Given a token exists with audience="did:key:bob"
    
    Creates a token with Bob as audience and returns it.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError


@pytest.fixture
def a_valid_token_exists_with_audiencedidkeybob(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice_and_private_key, audience_keypair_exists_with_diddidkeybob):
    """
    Given a valid token exists with audience="did:key:bob"
    
    Creates a valid token with Bob as audience and returns it.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError


@pytest.fixture
def a_token_exists_with_token_idtoken123(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice_and_private_key, audience_keypair_exists_with_diddidkeybob):
    """
    Given a token exists with token_id="token-123"
    
    Creates a token and returns it.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError


@pytest.fixture
def the_token_is_signed_and_not_expired():
    """
    Given the token is signed and not expired
    
    Returns True to indicate token validity requirements.
    """
    return True


@pytest.fixture
def the_token_is_valid_and_not_expired():
    """
    Given the token is valid and not expired
    
    Returns True to indicate token validity requirements.
    """
    return True


@pytest.fixture
def the_token_has_2_capabilities():
    """
    Given the token has 2 capabilities
    
    Returns 2 to indicate the number of capabilities.
    """
    return 2


@pytest.fixture
def the_token_issuer_is_didkeyalice():
    """
    Given the token issuer is "did:key:alice"
    
    Returns the issuer DID string.
    """
    return "did:key:alice"


@pytest.fixture
def the_token_audience_is_didkeybob():
    """
    Given the token audience is "did:key:bob"
    
    Returns the audience DID string.
    """
    return "did:key:bob"


# =============================================================================
# Collection Fixtures
# =============================================================================

@pytest.fixture
def three_keypairs_are_stored_with_dids_didkeyalice_didkeybob_didkeycharlie(a_ucanmanager_instance_is_initialized):
    """
    Given 3 keypairs are stored with DIDs "did:key:alice", "did:key:bob", "did:key:charlie"
    
    Creates 3 keypairs and stores them in the manager.
    Raises FixtureError if keypair creation fails.
    """
    try:
        manager = a_ucanmanager_instance_is_initialized
        
        # Generate 3 keypairs
        keypairs = []
        for i in range(3):
            keypair = manager.generate_keypair()
            if not keypair.did:
                raise FixtureError(f'Failed to create fixture three_keypairs_are_stored_with_dids_didkeyalice_didkeybob_didkeycharlie: Keypair {i} missing did') from None
            keypairs.append(keypair)
        
        # Verify 3 keypairs were created
        if len(keypairs) != 3:
            raise FixtureError(f'Failed to create fixture three_keypairs_are_stored_with_dids_didkeyalice_didkeybob_didkeycharlie: Expected 3 keypairs, got {len(keypairs)}') from None
        
        return keypairs
    except FixtureError:
        raise
    except Exception as e:
        raise FixtureError(f'Failed to create fixture three_keypairs_are_stored_with_dids_didkeyalice_didkeybob_didkeycharlie: {e}') from e


@pytest.fixture
def three_tokens_are_stored_with_ids_token1_token2_token3(a_ucanmanager_instance_is_initialized, issuer_keypair_exists_with_diddidkeyalice_and_private_key, audience_keypair_exists_with_diddidkeybob):
    """
    Given 3 tokens are stored with IDs "token-1", "token-2", "token-3"
    
    Creates 3 tokens and stores them in the manager.
    Raises FixtureError if token creation fails.
    """
    raise NotImplementedError
