"""
Comprehensive test suite for secure secrets management.

Tests cover:
    - Secret encryption and decryption
    - Secret creation, retrieval, deletion, and rotation
    - Secret persistence to disk
    - File permissions
    - Audit logging
    - Secret metadata and expiration
    - Exception handling
    - Convenience functions
"""

import pytest
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from ipfs_datasets_py.optimizers.security.secrets_manager import (
    SecretsManager,
    SecretEncryption,
    SecretMetadata,
    SecretAccessLog,
    SecretCategory,
    SecretAccessLevel,
    SecretsError,
    SecretNotFoundError,
    SecretExpiredError,
    InsufficientPermissionsError,
    load_secrets_from_env,
    validate_secret_strength,
    DEFAULT_SECRET_EXPIRY_DAYS,
)


class TestSecretEncryption:
    """Test suite for SecretEncryption class."""
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encrypting and decrypting returns original text."""
        encryption = SecretEncryption("test_master_key")
        plaintext = "my_secret_password"
        encrypted = encryption.encrypt(plaintext)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == plaintext
    
    def test_encrypt_produces_different_output(self):
        """Test encryption produces different output than input."""
        encryption = SecretEncryption("test_master_key")
        plaintext = "secret123"
        encrypted = encryption.encrypt(plaintext)
        assert encrypted != plaintext
    
    def test_encrypt_same_input_different_output(self):
        """Test encrypting same input twice produces different ciphertext."""
        encryption = SecretEncryption("test_master_key")
        plaintext = "secret"
        encrypted1 = encryption.encrypt(plaintext)
        encrypted2 = encryption.encrypt(plaintext)
        # Fernet includes timestamp, so outputs differ
        assert encrypted1 != encrypted2
    
    def test_decrypt_with_wrong_key_fails(self):
        """Test decrypting with wrong key fails."""
        encryption1 = SecretEncryption("key1")
        encryption2 = SecretEncryption("key2")
        encrypted = encryption1.encrypt("secret")
        with pytest.raises(Exception):  # Fernet raises InvalidToken
            encryption2.decrypt(encrypted)
    
    def test_encrypt_empty_string(self):
        """Test encrypting empty string."""
        encryption = SecretEncryption("test_master_key")
        encrypted = encryption.encrypt("")
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == ""
    
    def test_encrypt_unicode_text(self):
        """Test encrypting unicode text."""
        encryption = SecretEncryption("test_master_key")
        plaintext = "🔐 Secret with émojis and àccents"
        encrypted = encryption.encrypt(plaintext)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == plaintext
    
    def test_generate_key_creates_valid_key(self):
        """Test key generation creates valid Fernet key."""
        key = SecretEncryption.generate_key()
        assert isinstance(key, str)
        assert len(key) > 20  # Fernet keys are base64 encoded, 44 chars
        # Should be usable for encryption
        encryption = SecretEncryption(key)
        encryption.encrypt("test")
    
    def test_generate_key_creates_unique_keys(self):
        """Test each key generation is unique."""
        key1 = SecretEncryption.generate_key()
        key2 = SecretEncryption.generate_key()
        assert key1 != key2


class TestSecretsManager:
    """Test suite for SecretsManager class."""
    
    def test_set_secret_basic(self, tmp_path):
        """Test setting a basic secret."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta = manager.set_secret("api_key", "secret123")
        assert meta.name == "api_key"
        assert meta.version == 1
    
    def test_set_secret_with_category(self, tmp_path):
        """Test setting secret with category."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta = manager.set_secret(
            "db_password",
            "pass123",
            category=SecretCategory.DATABASE
        )
        assert meta.category == SecretCategory.DATABASE
    
    def test_set_secret_with_expiry(self, tmp_path):
        """Test setting secret with expiration."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta = manager.set_secret(
            "temp_key",
            "temp123",
            expires_in_days=30
        )
        assert meta.expires_at is not None
        assert meta.expires_at > datetime.utcnow()
    
    def test_set_secret_with_tags(self, tmp_path):
        """Test setting secret with tags."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta = manager.set_secret(
            "tagged_secret",
            "value",
            tags=["production", "critical"]
        )
        assert "production" in meta.tags
        assert "critical" in meta.tags
    
    def test_get_secret_basic(self, tmp_path):
        """Test retrieving a secret."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("api_key", "secret123")
        retrieved = manager.get_secret("api_key")
        assert retrieved == "secret123"
    
    def test_get_secret_not_found(self, tmp_path):
        """Test retrieving non-existent secret raises error."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        with pytest.raises(SecretNotFoundError, match="not found"):
            manager.get_secret("nonexistent")
    
    def test_get_secret_expired_raises_error(self, tmp_path):
        """Test retrieving expired secret raises error."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        # Set secret with past expiration
        meta = manager.set_secret("expired_key", "value")
        meta.expires_at = datetime.utcnow() - timedelta(days=1)
        manager._metadata["expired_key"] = meta
        
        with pytest.raises(SecretExpiredError, match="expired"):
            manager.get_secret("expired_key")
    
    def test_get_secret_with_access_level(self, tmp_path):
        """Test retrieving secret with access level check."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret(
            "restricted_key",
            "value",
            access_level=SecretAccessLevel.RESTRICTED
        )
        # Should fail if required access doesn't match
        with pytest.raises(InsufficientPermissionsError):
            manager.get_secret(
                "restricted_key",
                required_access=SecretAccessLevel.CONFIDENTIAL
            )
    
    def test_delete_secret_basic(self, tmp_path):
        """Test deleting a secret."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("to_delete", "value")
        manager.delete_secret("to_delete")
        
        with pytest.raises(SecretNotFoundError):
            manager.get_secret("to_delete")
    
    def test_delete_secret_not_found(self, tmp_path):
        """Test deleting non-existent secret raises error."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        with pytest.raises(SecretNotFoundError):
            manager.delete_secret("nonexistent")
    
    def test_rotate_secret_basic(self, tmp_path):
        """Test rotating a secret to new value."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("api_key", "old_secret")
        meta = manager.rotate_secret("api_key", "new_secret")
        
        assert meta.version == 2
        retrieved = manager.get_secret("api_key")
        assert retrieved == "new_secret"
    
    def test_rotate_secret_not_found(self, tmp_path):
        """Test rotating non-existent secret raises error."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        with pytest.raises(SecretNotFoundError):
            manager.rotate_secret("nonexistent", "new_value")
    
    def test_rotate_secret_increments_version(self, tmp_path):
        """Test rotating secret increments version each time."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "v1")
        manager.rotate_secret("key", "v2")
        meta = manager.rotate_secret("key", "v3")
        assert meta.version == 3
    
    def test_list_secrets_all(self, tmp_path):
        """Test listing all secrets."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key1", "value1")
        manager.set_secret("key2", "value2")
        manager.set_secret("key3", "value3")
        
        secrets = manager.list_secrets()
        assert len(secrets) == 3
    
    def test_list_secrets_by_category(self, tmp_path):
        """Test listing secrets filtered by category."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("db1", "val", category=SecretCategory.DATABASE)
        manager.set_secret("db2", "val", category=SecretCategory.DATABASE)
        manager.set_secret("api1", "val", category=SecretCategory.API_KEY)
        
        db_secrets = manager.list_secrets(category=SecretCategory.DATABASE)
        assert len(db_secrets) == 2
        assert all(s.category == SecretCategory.DATABASE for s in db_secrets)
    
    def test_list_secrets_exclude_expired(self, tmp_path):
        """Test listing secrets excludes expired by default."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("active", "val")
        meta = manager.set_secret("expired", "val")
        meta.expires_at = datetime.utcnow() - timedelta(days=1)
        manager._metadata["expired"] = meta
        
        secrets = manager.list_secrets(include_expired=False)
        assert len(secrets) == 1
        assert secrets[0].name == "active"
    
    def test_list_secrets_include_expired(self, tmp_path):
        """Test listing secrets can include expired."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("active", "val")
        meta = manager.set_secret("expired", "val")
        meta.expires_at = datetime.utcnow() - timedelta(days=1)
        manager._metadata["expired"] = meta
        
        secrets = manager.list_secrets(include_expired=True)
        assert len(secrets) == 2
    
    def test_get_metadata_basic(self, tmp_path):
        """Test retrieving secret metadata."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "value", description="Test secret")
        meta = manager.get_metadata("key")
        assert meta.name == "key"
        assert meta.description == "Test secret"
    
    def test_get_metadata_not_found(self, tmp_path):
        """Test retrieving metadata for non-existent secret."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        with pytest.raises(SecretNotFoundError):
            manager.get_metadata("nonexistent")


class TestSecretPersistence:
    """Test suite for secret persistence and file operations."""
    
    def test_save_secrets_creates_file(self, tmp_path):
        """Test saving secrets creates storage file."""
        vault_path = tmp_path / "vault.json"
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        manager.set_secret("key", "value")
        assert vault_path.exists()
    
    def test_save_secrets_creates_parent_dirs(self, tmp_path):
        """Test saving secrets creates parent directories."""
        vault_path = tmp_path / "nested" / "dir" / "vault.json"
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        manager.set_secret("key", "value")
        assert vault_path.exists()
    
    def test_save_secrets_file_permissions(self, tmp_path):
        """Test saved file has restrictive permissions."""
        vault_path = tmp_path / "vault.json"
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        manager.set_secret("key", "value")
        
        # Check file permissions (owner read/write only, 0o600)
        stat = vault_path.stat()
        mode = stat.st_mode & 0o777
        assert mode == 0o600
    
    def test_load_secrets_from_disk(self, tmp_path):
        """Test loading secrets from existing file."""
        vault_path = tmp_path / "vault.json"
        
        # Create and save secrets
        manager1 = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        manager1.set_secret("key1", "value1")
        manager1.set_secret("key2", "value2")
        
        # Load in new manager instance
        manager2 = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        assert manager2.get_secret("key1") == "value1"
        assert manager2.get_secret("key2") == "value2"
    
    def test_load_secrets_preserves_metadata(self, tmp_path):
        """Test loading secrets preserves metadata."""
        vault_path = tmp_path / "vault.json"
        
        manager1 = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        manager1.set_secret(
            "key",
            "value",
            category=SecretCategory.API_KEY,
            description="Test description",
            tags=["tag1", "tag2"]
        )
        
        manager2 = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        meta = manager2.get_metadata("key")
        assert meta.category == SecretCategory.API_KEY
        assert meta.description == "Test description"
        assert "tag1" in meta.tags
    
    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from non-existent file doesn't error."""
        vault_path = tmp_path / "nonexistent.json"
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=vault_path
        )
        # Should initialize with empty secrets
        assert len(manager.list_secrets()) == 0
    
    def test_shared_storage_across_managers(self, tmp_path):
        """Test multiple managers can share storage."""
        vault_path = tmp_path / "shared_vault.json"
        
        manager1 = SecretsManager(
            encryption_key="shared_key",
            storage_path=vault_path
        )
        manager1.set_secret("shared", "secret123")
        
        manager2 = SecretsManager(
            encryption_key="shared_key",
            storage_path=vault_path
        )
        assert manager2.get_secret("shared") == "secret123"


class TestAuditLog:
    """Test suite for audit logging functionality."""
    
    def test_audit_log_enabled_by_default(self, tmp_path):
        """Test audit logging is enabled by default."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        assert manager.enable_audit_log is True
    
    def test_audit_log_set_secret(self, tmp_path):
        """Test audit log records secret creation."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "value", user_id="alice")
        logs = manager.get_audit_log()
        assert len(logs) > 0
        assert logs[-1].operation == "write"
        assert logs[-1].secret_name == "key"
        assert logs[-1].user_id == "alice"
    
    def test_audit_log_get_secret(self, tmp_path):
        """Test audit log records secret retrieval."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "value")
        manager.get_secret("key", user_id="bob")
        
        logs = manager.get_audit_log()
        read_logs = [log for log in logs if log.operation == "read"]
        assert len(read_logs) > 0
        assert read_logs[-1].user_id == "bob"
    
    def test_audit_log_delete_secret(self, tmp_path):
        """Test audit log records secret deletion."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "value")
        manager.delete_secret("key", user_id="charlie")
        
        logs = manager.get_audit_log()
        delete_logs = [log for log in logs if log.operation == "delete"]
        assert len(delete_logs) > 0
        assert delete_logs[-1].user_id == "charlie"
    
    def test_audit_log_rotate_secret(self, tmp_path):
        """Test audit log records secret rotation."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key", "value1")
        manager.rotate_secret("key", "value2", user_id="dave")
        
        logs = manager.get_audit_log()
        rotate_logs = [log for log in logs if log.operation == "rotate"]
        assert len(rotate_logs) > 0
        assert rotate_logs[-1].user_id == "dave"
    
    def test_audit_log_failed_access(self, tmp_path):
        """Test audit log records failed access attempts."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        try:
            manager.get_secret("nonexistent", user_id="eve")
        except SecretNotFoundError:
            pass
        
        logs = manager.get_audit_log()
        failed_logs = [log for log in logs if not log.success]
        assert len(failed_logs) > 0
        assert failed_logs[-1].user_id == "eve"
    
    def test_audit_log_filter_by_secret_name(self, tmp_path):
        """Test filtering audit log by secret name."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key1", "value1")
        manager.set_secret("key2", "value2")
        manager.get_secret("key1")
        
        logs = manager.get_audit_log(secret_name="key1")
        assert all(log.secret_name == "key1" for log in logs)
    
    def test_audit_log_filter_by_user_id(self, tmp_path):
        """Test filtering audit log by user ID."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret("key1", "value1", user_id="alice")
        manager.set_secret("key2", "value2", user_id="bob")
        
        logs = manager.get_audit_log(user_id="alice")
        assert all(log.user_id == "alice" for log in logs)
    
    def test_audit_log_limit(self, tmp_path):
        """Test audit log respects limit parameter."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        for i in range(20):
            manager.set_secret(f"key{i}", f"value{i}")
        
        logs = manager.get_audit_log(limit=5)
        assert len(logs) == 5


class TestSecretMetadata:
    """Test suite for SecretMetadata functionality."""
    
    def test_is_expired_not_expired(self):
        """Test is_expired returns False for non-expired secret."""
        meta = SecretMetadata(
            name="test",
            category=SecretCategory.OTHER,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        assert meta.is_expired() is False
    
    def test_is_expired_expired(self):
        """Test is_expired returns True for expired secret."""
        meta = SecretMetadata(
            name="test",
            category=SecretCategory.OTHER,
            expires_at=datetime.utcnow() - timedelta(days=1)
        )
        assert meta.is_expired() is True
    
    def test_is_expired_no_expiry(self):
        """Test is_expired returns False when no expiration set."""
        meta = SecretMetadata(
            name="test",
            category=SecretCategory.OTHER,
            expires_at=None
        )
        assert meta.is_expired() is False
    
    def test_version_tracking(self, tmp_path):
        """Test version increments with updates."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta1 = manager.set_secret("key", "value1")
        assert meta1.version == 1
        
        meta2 = manager.set_secret("key", "value2")
        assert meta2.version == 2
    
    def test_created_at_timestamp(self, tmp_path):
        """Test created_at timestamp is set."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        before = datetime.utcnow()
        meta = manager.set_secret("key", "value")
        after = datetime.utcnow()
        
        assert before <= meta.created_at <= after
    
    def test_updated_at_timestamp(self, tmp_path):
        """Test updated_at timestamp changes on rotation."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta1 = manager.set_secret("key", "value1")
        original_updated = meta1.updated_at
        
        # Small delay to ensure different timestamp
        import time
        time.sleep(0.01)
        
        meta2 = manager.rotate_secret("key", "value2")
        assert meta2.updated_at > original_updated


class TestConvenienceFunctions:
    """Test suite for convenience functions."""
    
    def test_load_secrets_from_env_with_prefix(self):
        """Test loading secrets from environment variables."""
        with patch.dict(os.environ, {
            "SECRET_API_KEY": "key123",
            "SECRET_DB_PASSWORD": "pass456",
            "OTHER_VAR": "not_a_secret"
        }):
            secrets = load_secrets_from_env(prefix="SECRET_")
            assert "api_key" in secrets
            assert secrets["api_key"] == "key123"
            assert "db_password" in secrets
            assert secrets["db_password"] == "pass456"
            assert "other_var" not in secrets
    
    def test_load_secrets_from_env_custom_prefix(self):
        """Test loading secrets with custom prefix."""
        with patch.dict(os.environ, {
            "MYAPP_TOKEN": "token123",
            "MYAPP_SECRET": "secret456",
            "SECRET_OTHER": "not_loaded"
        }):
            secrets = load_secrets_from_env(prefix="MYAPP_")
            assert "token" in secrets
            assert "secret" in secrets
            assert "other" not in secrets
    
    def test_load_secrets_from_env_empty(self):
        """Test loading when no matching env vars exist."""
        with patch.dict(os.environ, {"OTHER_VAR": "value"}, clear=True):
            secrets = load_secrets_from_env(prefix="SECRET_")
            assert len(secrets) == 0
    
    def test_validate_secret_strength_strong(self):
        """Test strong secret passes validation."""
        assert validate_secret_strength("MyStr0ng!P@ssw0rd") is True
    
    def test_validate_secret_strength_too_short(self):
        """Test short secret fails validation."""
        assert validate_secret_strength("Short1!") is False
    
    def test_validate_secret_strength_no_uppercase(self):
        """Test secret without uppercase fails."""
        assert validate_secret_strength("weak1password!!!!") is False
    
    def test_validate_secret_strength_no_lowercase(self):
        """Test secret without lowercase fails."""
        assert validate_secret_strength("WEAK1PASSWORD!!!!") is False
    
    def test_validate_secret_strength_no_digits(self):
        """Test secret without digits fails."""
        assert validate_secret_strength("WeakPassword!!!!") is False
    
    def test_validate_secret_strength_no_special(self):
        """Test secret without special chars fails."""
        assert validate_secret_strength("WeakPassword1234") is False
    
    def test_validate_secret_strength_custom_min_length(self):
        """Test custom minimum length requirement."""
        assert validate_secret_strength("Str0ng!", min_length=8) is False
        assert validate_secret_strength("Str0ng!P", min_length=8) is True


class TestExceptionsAndErrors:
    """Test suite for exception handling."""
    
    def test_secret_not_found_error(self, tmp_path):
        """Test SecretNotFoundError is raised correctly."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        with pytest.raises(SecretNotFoundError) as exc_info:
            manager.get_secret("nonexistent")
        assert "not found" in str(exc_info.value)
    
    def test_secret_expired_error(self, tmp_path):
        """Test SecretExpiredError is raised correctly."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        meta = manager.set_secret("key", "value")
        meta.expires_at = datetime.utcnow() - timedelta(days=1)
        manager._metadata["key"] = meta
        
        with pytest.raises(SecretExpiredError) as exc_info:
            manager.get_secret("key")
        assert "expired" in str(exc_info.value)
    
    def test_insufficient_permissions_error(self, tmp_path):
        """Test InsufficientPermissionsError is raised correctly."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        manager.set_secret(
            "key",
            "value",
            access_level=SecretAccessLevel.RESTRICTED
        )
        
        with pytest.raises(InsufficientPermissionsError) as exc_info:
            manager.get_secret("key", required_access=SecretAccessLevel.PUBLIC)
        assert "Insufficient" in str(exc_info.value)
    
    def test_secrets_error_base_class(self):
        """Test SecretsError is base class for all errors."""
        assert issubclass(SecretNotFoundError, SecretsError)
        assert issubclass(SecretExpiredError, SecretsError)
        assert issubclass(InsufficientPermissionsError, SecretsError)


class TestSecretCategories:
    """Test secret category functionality."""
    
    def test_all_categories_available(self, tmp_path):
        """Test all secret categories can be used."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        categories = [
            SecretCategory.DATABASE,
            SecretCategory.API_KEY,
            SecretCategory.ENCRYPTION_KEY,
            SecretCategory.CREDENTIALS,
            SecretCategory.TOKEN,
            SecretCategory.CERTIFICATE,
            SecretCategory.OTHER,
        ]
        for i, category in enumerate(categories):
            manager.set_secret(f"key{i}", f"value{i}", category=category)
            meta = manager.get_metadata(f"key{i}")
            assert meta.category == category


class TestAccessLevels:
    """Test secret access level functionality."""
    
    def test_all_access_levels_available(self, tmp_path):
        """Test all access levels can be used."""
        manager = SecretsManager(
            encryption_key="test_key",
            storage_path=tmp_path / "vault.json"
        )
        levels = [
            SecretAccessLevel.PUBLIC,
            SecretAccessLevel.INTERNAL,
            SecretAccessLevel.CONFIDENTIAL,
            SecretAccessLevel.RESTRICTED,
        ]
        for i, level in enumerate(levels):
            manager.set_secret(f"key{i}", f"value{i}", access_level=level)
            meta = manager.get_metadata(f"key{i}")
            assert meta.access_level == level
