"""
Secure secrets management module for storing and managing sensitive data.

This module provides comprehensive secrets management with:
    - Encryption using Fernet (symmetric encryption)
    - Persistent storage with secure file permissions
    - Audit logging for compliance
    - Secret rotation and versioning
    - Expiration management
    - Access level controls
    - Category-based organization

Example:
    Basic usage:
    
    >>> from ipfs_datasets_py.optimizers.security.secrets_manager import SecretsManager
    >>> manager = SecretsManager("my_encryption_key", "vault.json")
    >>> manager.set_secret("api_key", "secret_value_123")
    >>> secret = manager.get_secret("api_key")
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field, asdict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from ipfs_datasets_py.optimizers.common.path_validator import (
    validate_input_path,
    validate_output_path,
)


# Constants
DEFAULT_SECRET_EXPIRY_DAYS = 90


# Enums
class SecretCategory(Enum):
    """Categories of secrets for organizational purposes."""
    DATABASE = "database"
    API_KEY = "api_key"
    ENCRYPTION_KEY = "encryption_key"
    CREDENTIALS = "credentials"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    OTHER = "other"


class SecretAccessLevel(Enum):
    """Access levels for secrets with increasing restrictions."""
    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    RESTRICTED = 4


# Exceptions
class SecretsError(Exception):
    """Base exception for all secrets-related errors."""
    pass


class SecretNotFoundError(SecretsError):
    """Raised when a requested secret does not exist."""
    pass


class SecretExpiredError(SecretsError):
    """Raised when attempting to access an expired secret."""
    pass


class InsufficientPermissionsError(SecretsError):
    """Raised when user doesn't have sufficient access level for a secret."""
    pass


# Data Classes
@dataclass
class SecretMetadata:
    """Metadata for a secret without the actual secret value."""
    name: str
    category: SecretCategory = SecretCategory.OTHER
    access_level: SecretAccessLevel = SecretAccessLevel.INTERNAL
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        """Check if the secret has expired.
        
        Returns:
            True if secret is expired, False otherwise.
        """
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        data['expires_at'] = self.expires_at.isoformat() if self.expires_at else None
        # Convert enums to strings
        data['category'] = self.category.value
        data['access_level'] = self.access_level.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SecretMetadata':
        """Create metadata from dictionary."""
        # Convert ISO format strings to datetime objects
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        data['expires_at'] = datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None
        # Convert strings to enums
        data['category'] = SecretCategory(data['category'])
        data['access_level'] = SecretAccessLevel(data['access_level'])
        return cls(**data)


@dataclass
class SecretAccessLog:
    """Log entry for secret access audit trail."""
    timestamp: datetime
    operation: str  # read, write, delete, rotate
    secret_name: str
    user_id: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert log entry to dictionary for serialization."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SecretAccessLog':
        """Create log entry from dictionary."""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class SecretEncryption:
    """Handles encryption and decryption of secrets using Fernet."""

    def __init__(self, master_key: str):
        """Initialize encryption with a master key.
        
        Args:
            master_key: Master key used for encryption/decryption.
        """
        # Derive a proper Fernet key from the master key
        self._fernet = self._create_fernet(master_key)

    def _create_fernet(self, master_key: str) -> Fernet:
        """Create a Fernet instance from a master key.
        
        Args:
            master_key: The master key to derive Fernet key from.
            
        Returns:
            Fernet instance for encryption/decryption.
        """
        # Use PBKDF2 to derive a proper key from the master key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'secrets_manager_salt',  # In production, use random salt per installation
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.
        
        Args:
            plaintext: The text to encrypt.
            
        Returns:
            Encrypted text as a string.
        """
        encrypted_bytes = self._fernet.encrypt(plaintext.encode())
        return encrypted_bytes.decode()

    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted string.
        
        Args:
            encrypted: The encrypted text to decrypt.
            
        Returns:
            Decrypted plaintext string.
        """
        decrypted_bytes = self._fernet.decrypt(encrypted.encode())
        return decrypted_bytes.decode()

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet key.
        
        Returns:
            Base64-encoded Fernet key as a string.
        """
        key = Fernet.generate_key()
        return key.decode()


class SecretsManager:
    """Main class for managing secrets with encryption, persistence, and audit logging."""

    def __init__(
        self,
        encryption_key: str,
        storage_path: Path | str,
        enable_audit_log: bool = True
    ):
        """Initialize the secrets manager.
        
        Args:
            encryption_key: Master key for encrypting secrets.
            storage_path: Path to JSON file for persistent storage.
            enable_audit_log: Whether to enable audit logging.
        """
        self.encryption = SecretEncryption(encryption_key)
        self.storage_path = Path(storage_path)
        self.enable_audit_log = enable_audit_log

        # Internal state
        self._secrets: Dict[str, str] = {}  # name -> encrypted_value
        self._metadata: Dict[str, SecretMetadata] = {}  # name -> metadata
        self._audit_log: List[SecretAccessLog] = []

        # Load existing secrets if available
        self._load_secrets()

    def set_secret(
        self,
        name: str,
        value: str,
        category: SecretCategory = SecretCategory.OTHER,
        access_level: SecretAccessLevel = SecretAccessLevel.INTERNAL,
        description: str = "",
        tags: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
        user_id: Optional[str] = None
    ) -> SecretMetadata:
        """Set or update a secret.
        
        Args:
            name: Name/key for the secret.
            value: The secret value to store.
            category: Category of the secret.
            access_level: Access level required to read the secret.
            description: Optional description of the secret.
            tags: Optional list of tags for organization.
            expires_in_days: Optional expiration in days from now.
            user_id: Optional user ID for audit logging.
            
        Returns:
            Metadata for the created/updated secret.
        """
        # Encrypt the value
        encrypted_value = self.encryption.encrypt(value)
        self._secrets[name] = encrypted_value

        # Create or update metadata
        if name in self._metadata:
            # Update existing secret - increment version
            meta = self._metadata[name]
            meta.version += 1
            meta.updated_at = datetime.utcnow()
            meta.description = description or meta.description
            meta.tags = tags if tags is not None else meta.tags
            meta.category = category
            meta.access_level = access_level
        else:
            # Create new secret
            meta = SecretMetadata(
                name=name,
                category=category,
                access_level=access_level,
                description=description,
                tags=tags or [],
                version=1
            )

        # Set expiration if specified
        if expires_in_days is not None:
            meta.expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        self._metadata[name] = meta

        # Log the operation
        self._log_access("write", name, user_id=user_id, success=True)

        # Persist to disk
        self._save_secrets()

        return meta

    def get_secret(
        self,
        name: str,
        required_access: Optional[SecretAccessLevel] = None,
        user_id: Optional[str] = None
    ) -> str:
        """Retrieve a secret value.
        
        Args:
            name: Name of the secret to retrieve.
            required_access: Required access level (for permission checks).
            user_id: Optional user ID for audit logging.
            
        Returns:
            The decrypted secret value.
            
        Raises:
            SecretNotFoundError: If secret doesn't exist.
            SecretExpiredError: If secret has expired.
            InsufficientPermissionsError: If access level is insufficient.
        """
        try:
            # Check if secret exists
            if name not in self._secrets:
                raise SecretNotFoundError(f"Secret '{name}' not found")

            meta = self._metadata[name]

            # Check expiration
            if meta.is_expired():
                raise SecretExpiredError(f"Secret '{name}' has expired")

            # Check access level permissions
            if required_access is not None:
                if meta.access_level.value < required_access.value:
                    raise InsufficientPermissionsError(
                        f"Insufficient permissions to access secret '{name}'. "
                        f"Required: {required_access.name}, Has: {meta.access_level.name}"
                    )

            # Decrypt and return
            encrypted_value = self._secrets[name]
            decrypted_value = self.encryption.decrypt(encrypted_value)

            # Log successful access
            self._log_access("read", name, user_id=user_id, success=True)

            return decrypted_value

        except (SecretNotFoundError, SecretExpiredError, InsufficientPermissionsError) as e:
            # Log failed access
            self._log_access("read", name, user_id=user_id, success=False, error_message=str(e))
            raise

    def delete_secret(self, name: str, user_id: Optional[str] = None) -> None:
        """Delete a secret.
        
        Args:
            name: Name of the secret to delete.
            user_id: Optional user ID for audit logging.
            
        Raises:
            SecretNotFoundError: If secret doesn't exist.
        """
        if name not in self._secrets:
            raise SecretNotFoundError(f"Secret '{name}' not found")

        # Remove the secret
        del self._secrets[name]
        del self._metadata[name]

        # Log the operation
        self._log_access("delete", name, user_id=user_id, success=True)

        # Persist to disk
        self._save_secrets()

    def rotate_secret(
        self,
        name: str,
        new_value: str,
        user_id: Optional[str] = None
    ) -> SecretMetadata:
        """Rotate a secret to a new value.
        
        Args:
            name: Name of the secret to rotate.
            new_value: New secret value.
            user_id: Optional user ID for audit logging.
            
        Returns:
            Updated metadata with incremented version.
            
        Raises:
            SecretNotFoundError: If secret doesn't exist.
        """
        if name not in self._secrets:
            raise SecretNotFoundError(f"Secret '{name}' not found")

        # Get existing metadata
        meta = self._metadata[name]

        # Update the secret value (encrypted)
        encrypted_value = self.encryption.encrypt(new_value)
        self._secrets[name] = encrypted_value

        # Update metadata
        meta.version += 1
        meta.updated_at = datetime.utcnow()
        self._metadata[name] = meta

        # Log the operation
        self._log_access("rotate", name, user_id=user_id, success=True)

        # Persist to disk
        self._save_secrets()

        return meta

    def list_secrets(
        self,
        category: Optional[SecretCategory] = None,
        include_expired: bool = False
    ) -> List[SecretMetadata]:
        """List all secrets with optional filtering.
        
        Args:
            category: Optional filter by category.
            include_expired: Whether to include expired secrets.
            
        Returns:
            List of secret metadata matching the criteria.
        """
        results = []

        for meta in self._metadata.values():
            # Filter by expiration
            if not include_expired and meta.is_expired():
                continue

            # Filter by category
            if category is not None and meta.category != category:
                continue

            results.append(meta)

        return results

    def get_metadata(self, name: str) -> SecretMetadata:
        """Get metadata for a secret without retrieving the value.
        
        Args:
            name: Name of the secret.
            
        Returns:
            Secret metadata.
            
        Raises:
            SecretNotFoundError: If secret doesn't exist.
        """
        if name not in self._metadata:
            raise SecretNotFoundError(f"Secret '{name}' not found")

        return self._metadata[name]

    def get_audit_log(
        self,
        secret_name: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[SecretAccessLog]:
        """Retrieve audit log entries with optional filtering.
        
        Args:
            secret_name: Optional filter by secret name.
            user_id: Optional filter by user ID.
            limit: Optional limit on number of entries returned.
            
        Returns:
            List of audit log entries matching criteria.
        """
        results = []

        for log_entry in self._audit_log:
            # Filter by secret name
            if secret_name is not None and log_entry.secret_name != secret_name:
                continue

            # Filter by user ID
            if user_id is not None and log_entry.user_id != user_id:
                continue

            results.append(log_entry)

        # Apply limit if specified
        if limit is not None:
            results = results[-limit:]

        return results

    def _log_access(
        self,
        operation: str,
        secret_name: str,
        user_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> None:
        """Log an access operation to the audit log.
        
        Args:
            operation: Type of operation (read, write, delete, rotate).
            secret_name: Name of the secret accessed.
            user_id: Optional user ID.
            success: Whether the operation succeeded.
            error_message: Optional error message if operation failed.
        """
        if not self.enable_audit_log:
            return

        log_entry = SecretAccessLog(
            timestamp=datetime.utcnow(),
            operation=operation,
            secret_name=secret_name,
            user_id=user_id,
            success=success,
            error_message=error_message
        )

        self._audit_log.append(log_entry)

    def _save_secrets(self) -> None:
        """Save secrets and metadata to persistent storage."""
        # Create parent directories if needed
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare data for serialization
        data = {
            'secrets': self._secrets,
            'metadata': {
                name: meta.to_dict()
                for name, meta in self._metadata.items()
            },
            'audit_log': [
                log.to_dict()
                for log in self._audit_log
            ]
        }

        # Write to file
        base_dir = self.storage_path.parent if self.storage_path.is_absolute() else None
        safe_path = validate_output_path(str(self.storage_path), allow_overwrite=True, base_dir=base_dir)
        with open(safe_path, 'w') as f:
            json.dump(data, f, indent=2)

        # Set restrictive file permissions (owner read/write only)
        Path(safe_path).chmod(0o600)

    def _load_secrets(self) -> None:
        """Load secrets and metadata from persistent storage."""
        if not self.storage_path.exists():
            return

        try:
            base_dir = self.storage_path.parent if self.storage_path.is_absolute() else None
            safe_path = validate_input_path(str(self.storage_path), must_exist=True, base_dir=base_dir)
            with open(safe_path, 'r') as f:
                data = json.load(f)

            # Load secrets
            self._secrets = data.get('secrets', {})

            # Load metadata
            metadata_dict = data.get('metadata', {})
            self._metadata = {
                name: SecretMetadata.from_dict(meta_data)
                for name, meta_data in metadata_dict.items()
            }

            # Load audit log
            audit_log_data = data.get('audit_log', [])
            self._audit_log = [
                SecretAccessLog.from_dict(log_data)
                for log_data in audit_log_data
            ]

        except (json.JSONDecodeError, KeyError) as e:
            # If file is corrupted, start fresh
            self._secrets = {}
            self._metadata = {}
            self._audit_log = []


# Convenience Functions
def load_secrets_from_env(prefix: str = "SECRET_") -> Dict[str, str]:
    """Load secrets from environment variables with a given prefix.
    
    Args:
        prefix: Prefix to filter environment variables (e.g., "SECRET_").
        
    Returns:
        Dictionary mapping secret names to values.
        
    Example:
        With env vars SECRET_API_KEY=abc123, SECRET_DB_PASSWORD=pass456:
        
        >>> secrets = load_secrets_from_env("SECRET_")
        >>> secrets
        {'api_key': 'abc123', 'db_password': 'pass456'}
    """
    secrets = {}

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Remove prefix and convert to lowercase with underscores
            secret_name = key[len(prefix):].lower()
            secrets[secret_name] = value

    return secrets


def validate_secret_strength(
    secret: str,
    min_length: int = 12,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digits: bool = True,
    require_special: bool = True
) -> bool:
    """Validate that a secret meets strength requirements.
    
    Args:
        secret: The secret to validate.
        min_length: Minimum length required.
        require_uppercase: Whether to require uppercase letters.
        require_lowercase: Whether to require lowercase letters.
        require_digits: Whether to require digits.
        require_special: Whether to require special characters.
        
    Returns:
        True if secret meets all requirements, False otherwise.
        
    Example:
        >>> validate_secret_strength("MyStr0ng!P@ssw0rd")
        True
        >>> validate_secret_strength("weak")
        False
    """
    # Check length
    if len(secret) < min_length:
        return False

    # Check uppercase
    if require_uppercase and not any(c.isupper() for c in secret):
        return False

    # Check lowercase
    if require_lowercase and not any(c.islower() for c in secret):
        return False

    # Check digits
    if require_digits and not any(c.isdigit() for c in secret):
        return False

    # Check special characters
    if require_special:
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?/"
        if not any(c in special_chars for c in secret):
            return False

    return True
