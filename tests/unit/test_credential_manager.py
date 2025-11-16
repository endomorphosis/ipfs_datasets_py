"""
Unit tests for credential manager module.
"""

import os
import tempfile
import time
import pytest
from pathlib import Path

try:
    from ipfs_datasets_py.credential_manager import (
        CredentialManager,
        Credential,
        CredentialScope,
        get_global_credential_manager,
        configure_credential_manager
    )
    HAVE_CREDENTIAL_MANAGER = True
except ImportError:
    HAVE_CREDENTIAL_MANAGER = False
    pytest.skip("cryptography not available", allow_module_level=True)


@pytest.mark.skipif(not HAVE_CREDENTIAL_MANAGER, reason="cryptography not available")
class TestCredential:
    """Test Credential dataclass."""
    
    def test_create_credential(self):
        """Test creating a credential."""
        cred = Credential(
            name="TEST_TOKEN",
            encrypted_value=b"encrypted",
            scope=CredentialScope.GLOBAL,
            scope_filter=None,
            created_at=time.time(),
            expires_at=None
        )
        
        assert cred.name == "TEST_TOKEN"
        assert cred.scope == CredentialScope.GLOBAL
        assert not cred.is_expired()
    
    def test_is_expired(self):
        """Test expiration checking."""
        # Non-expiring credential
        cred1 = Credential(
            name="TEST",
            encrypted_value=b"encrypted",
            scope=CredentialScope.GLOBAL,
            scope_filter=None,
            created_at=time.time(),
            expires_at=None
        )
        assert not cred1.is_expired()
        
        # Expired credential
        cred2 = Credential(
            name="TEST",
            encrypted_value=b"encrypted",
            scope=CredentialScope.GLOBAL,
            scope_filter=None,
            created_at=time.time(),
            expires_at=time.time() - 3600  # Expired 1 hour ago
        )
        assert cred2.is_expired()
        
        # Future expiration
        cred3 = Credential(
            name="TEST",
            encrypted_value=b"encrypted",
            scope=CredentialScope.GLOBAL,
            scope_filter=None,
            created_at=time.time(),
            expires_at=time.time() + 3600  # Expires in 1 hour
        )
        assert not cred3.is_expired()
    
    def test_matches_scope(self):
        """Test scope matching."""
        # Global scope - matches everything
        global_cred = Credential(
            name="GLOBAL",
            encrypted_value=b"encrypted",
            scope=CredentialScope.GLOBAL,
            scope_filter=None,
            created_at=time.time(),
            expires_at=None
        )
        assert global_cred.matches_scope()
        assert global_cred.matches_scope(repo="any/repo")
        assert global_cred.matches_scope(workflow="any-workflow")
        
        # Repo scope
        repo_cred = Credential(
            name="REPO",
            encrypted_value=b"encrypted",
            scope=CredentialScope.REPO,
            scope_filter="owner/repo",
            created_at=time.time(),
            expires_at=None
        )
        assert repo_cred.matches_scope(repo="owner/repo")
        assert not repo_cred.matches_scope(repo="other/repo")
        
        # Workflow scope
        workflow_cred = Credential(
            name="WORKFLOW",
            encrypted_value=b"encrypted",
            scope=CredentialScope.WORKFLOW,
            scope_filter="test-workflow",
            created_at=time.time(),
            expires_at=None
        )
        assert workflow_cred.matches_scope(workflow="test-workflow")
        assert not workflow_cred.matches_scope(workflow="other-workflow")


@pytest.mark.skipif(not HAVE_CREDENTIAL_MANAGER, reason="cryptography not available")
class TestCredentialManager:
    """Test CredentialManager class."""
    
    @pytest.fixture
    def temp_storage_dir(self):
        """Create temporary storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.fixture
    def manager(self, temp_storage_dir):
        """Create a CredentialManager instance for testing."""
        return CredentialManager(
            storage_dir=temp_storage_dir,
            use_keyring=False  # Disable keyring for tests
        )
    
    def test_initialize_manager(self, manager, temp_storage_dir):
        """Test manager initialization."""
        assert manager.storage_dir == Path(temp_storage_dir)
        assert manager.master_key is not None
        assert len(manager.master_key) == 32  # 256 bits
        assert manager.storage_dir.exists()
    
    def test_store_and_get_credential(self, manager):
        """Test storing and retrieving credentials."""
        # Store credential
        manager.store_credential(
            name="TEST_TOKEN",
            value="secret_value_123",
            scope=CredentialScope.GLOBAL
        )
        
        # Retrieve credential
        value = manager.get_credential("TEST_TOKEN")
        
        assert value == "secret_value_123"
    
    def test_store_scoped_credential(self, manager):
        """Test storing scoped credentials."""
        # Store repo-scoped credential
        manager.store_credential(
            name="REPO_TOKEN",
            value="repo_secret",
            scope=CredentialScope.REPO,
            scope_filter="owner/repo"
        )
        
        # Should work with matching scope
        value = manager.get_credential(
            "REPO_TOKEN",
            repo="owner/repo"
        )
        assert value == "repo_secret"
        
        # Should fail with wrong scope
        value = manager.get_credential(
            "REPO_TOKEN",
            repo="other/repo"
        )
        assert value is None
    
    def test_credential_expiration(self, manager):
        """Test credential expiration."""
        # Store credential with short TTL
        manager.store_credential(
            name="EXPIRING",
            value="temp_value",
            ttl_hours=0.0001  # ~0.36 seconds
        )
        
        # Should work immediately
        value = manager.get_credential("EXPIRING")
        assert value == "temp_value"
        
        # Wait for expiration
        time.sleep(1)
        
        # Should be expired now
        value = manager.get_credential("EXPIRING")
        assert value is None
    
    def test_rotate_credential(self, manager):
        """Test credential rotation."""
        # Store original credential
        manager.store_credential(
            name="ROTATE_TEST",
            value="original_value"
        )
        
        # Verify original value
        value = manager.get_credential("ROTATE_TEST")
        assert value == "original_value"
        
        # Rotate to new value
        success = manager.rotate_credential(
            "ROTATE_TEST",
            "new_value"
        )
        assert success
        
        # Verify new value
        value = manager.get_credential("ROTATE_TEST")
        assert value == "new_value"
    
    def test_delete_credential(self, manager):
        """Test credential deletion."""
        # Store credential
        manager.store_credential(
            name="TO_DELETE",
            value="delete_me"
        )
        
        # Verify it exists
        value = manager.get_credential("TO_DELETE")
        assert value == "delete_me"
        
        # Delete it
        success = manager.delete_credential("TO_DELETE")
        assert success
        
        # Verify it's gone
        value = manager.get_credential("TO_DELETE")
        assert value is None
        
        # Try to delete again
        success = manager.delete_credential("TO_DELETE")
        assert not success
    
    def test_list_credentials(self, manager):
        """Test listing credentials."""
        # Store multiple credentials
        manager.store_credential("CRED1", "value1")
        manager.store_credential("CRED2", "value2", ttl_hours=24)
        manager.store_credential("CRED3", "value3", ttl_hours=0.0001)
        
        time.sleep(1)  # Let CRED3 expire
        
        # List without expired
        creds = manager.list_credentials(include_expired=False)
        names = [c['name'] for c in creds]
        
        assert "CRED1" in names
        assert "CRED2" in names
        assert "CRED3" not in names
        
        # List with expired
        creds = manager.list_credentials(include_expired=True)
        names = [c['name'] for c in creds]
        
        assert "CRED1" in names
        assert "CRED2" in names
        assert "CRED3" in names
    
    def test_cleanup_expired(self, manager):
        """Test cleaning up expired credentials."""
        # Store credentials
        manager.store_credential("KEEP", "value1")
        manager.store_credential("EXPIRE1", "value2", ttl_hours=0.0001)
        manager.store_credential("EXPIRE2", "value3", ttl_hours=0.0001)
        
        time.sleep(1)  # Let credentials expire
        
        # Cleanup
        removed = manager.cleanup_expired()
        
        assert removed == 2
        
        # Verify non-expired still exists
        value = manager.get_credential("KEEP")
        assert value == "value1"
        
        # Verify expired are gone
        value = manager.get_credential("EXPIRE1")
        assert value is None
    
    def test_persistence(self, temp_storage_dir):
        """Test credential persistence across manager instances."""
        # Create manager and store credential
        manager1 = CredentialManager(
            storage_dir=temp_storage_dir,
            use_keyring=False
        )
        manager1.store_credential("PERSIST", "persistent_value")
        
        # Create new manager with same storage
        manager2 = CredentialManager(
            storage_dir=temp_storage_dir,
            use_keyring=False
        )
        
        # Should load credential from disk
        value = manager2.get_credential("PERSIST")
        assert value == "persistent_value"
    
    def test_get_stats(self, manager):
        """Test statistics collection."""
        # Initial stats
        stats = manager.get_stats()
        assert stats["credentials_stored"] == 0
        
        # Store credentials
        manager.store_credential("CRED1", "value1")
        manager.store_credential("CRED2", "value2", ttl_hours=0.0001)
        
        time.sleep(1)  # Let one expire
        
        # Check stats
        stats = manager.get_stats()
        assert stats["credentials_stored"] == 2
        assert stats["active_credentials"] == 1
        assert stats["expired_credentials"] == 1
        
        # Access credential
        manager.get_credential("CRED1")
        
        stats = manager.get_stats()
        assert stats["credentials_accessed"] == 1
    
    def test_encryption_decryption(self, manager):
        """Test encryption and decryption."""
        # Test various value types
        test_values = [
            "simple_string",
            "string with spaces and $pecial ch@rs!",
            "very" * 100,  # Long string
            "unicode: 你好世界 🌍",
        ]
        
        for i, value in enumerate(test_values):
            name = f"TEST_{i}"
            manager.store_credential(name, value)
            retrieved = manager.get_credential(name)
            assert retrieved == value


@pytest.mark.skipif(not HAVE_CREDENTIAL_MANAGER, reason="cryptography not available")
class TestGlobalManager:
    """Test global credential manager instance."""
    
    def test_get_global_manager(self):
        """Test getting global manager instance."""
        manager1 = get_global_credential_manager()
        manager2 = get_global_credential_manager()
        
        # Should return same instance
        assert manager1 is manager2
    
    def test_configure_manager(self):
        """Test configuring global manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = configure_credential_manager(
                storage_dir=tmpdir,
                use_keyring=False
            )
            
            assert manager.storage_dir == Path(tmpdir)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
