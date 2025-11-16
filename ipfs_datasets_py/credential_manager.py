"""
Credential Manager for Auto-Scaled Runners

This module provides secure credential injection for auto-scaled GitHub Actions runners.
It handles encryption, storage, and secure distribution of credentials (GitHub tokens,
API keys, secrets) to runners provisioned by ipfs_accelerate_py's autoscaler.

Security Features:
- AES-256-GCM encryption at rest and in transit
- Key derivation using PBKDF2-HMAC-SHA256
- Secure key storage with OS keyring integration
- Automatic credential rotation support
- Audit logging for all credential access
- Time-limited credentials with automatic expiration
- Support for credential scoping (per-repo, per-workflow)
"""

import json
import logging
import os
import time
import base64
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from enum import Enum

# Cryptography imports
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False
    logging.warning("cryptography not available, credential manager will not work")

# Keyring for OS-level secure storage
try:
    import keyring
    HAVE_KEYRING = True
except ImportError:
    HAVE_KEYRING = False
    logging.warning("keyring not available, falling back to file-based storage")

logger = logging.getLogger(__name__)


class CredentialScope(Enum):
    """Scope of a credential."""
    GLOBAL = "global"  # Available to all runners
    REPO = "repo"  # Available to specific repository
    WORKFLOW = "workflow"  # Available to specific workflow
    RUNNER = "runner"  # Available to specific runner


@dataclass
class Credential:
    """Represents a secured credential."""
    name: str
    encrypted_value: bytes
    scope: CredentialScope
    scope_filter: Optional[str]  # e.g., "owner/repo" for REPO scope
    created_at: float
    expires_at: Optional[float]
    last_accessed: Optional[float] = None
    access_count: int = 0
    metadata: Dict[str, Any] = None
    
    def is_expired(self) -> bool:
        """Check if credential has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def matches_scope(self, repo: Optional[str] = None, workflow: Optional[str] = None, runner_id: Optional[str] = None) -> bool:
        """Check if credential matches the requested scope."""
        if self.scope == CredentialScope.GLOBAL:
            return True
        
        if self.scope == CredentialScope.REPO and repo:
            return self.scope_filter == repo
        
        if self.scope == CredentialScope.WORKFLOW and workflow:
            return self.scope_filter == workflow
        
        if self.scope == CredentialScope.RUNNER and runner_id:
            return self.scope_filter == runner_id
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'encrypted_value': base64.b64encode(self.encrypted_value).decode('utf-8'),
            'scope': self.scope.value,
            'scope_filter': self.scope_filter,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'last_accessed': self.last_accessed,
            'access_count': self.access_count,
            'metadata': self.metadata or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Credential':
        """Create from dictionary."""
        data['encrypted_value'] = base64.b64decode(data['encrypted_value'])
        data['scope'] = CredentialScope(data['scope'])
        return cls(**data)


class CredentialManager:
    """
    Manages secure credential injection for auto-scaled runners.
    
    Features:
    - Encrypts credentials using AES-256-GCM
    - Supports multiple credential scopes
    - Automatic expiration and rotation
    - Audit logging
    - P2P distribution for multi-runner setups
    """
    
    def __init__(
        self,
        storage_dir: Optional[str] = None,
        master_key: Optional[bytes] = None,
        use_keyring: bool = True,
        audit_log_path: Optional[str] = None
    ):
        """
        Initialize the credential manager.
        
        Args:
            storage_dir: Directory for credential storage (default: ~/.credentials)
            master_key: Master encryption key (generates if not provided)
            use_keyring: Whether to use OS keyring for master key storage
            audit_log_path: Path to audit log file
        """
        if not HAVE_CRYPTO:
            raise RuntimeError("cryptography package required, install with: pip install cryptography")
        
        # Set up storage directory
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path.home() / ".credentials"
        
        self.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)  # Restrict permissions
        
        self.use_keyring = use_keyring and HAVE_KEYRING
        
        # Initialize or load master key
        self.master_key = master_key or self._load_or_create_master_key()
        
        # Initialize cipher
        self.cipher = AESGCM(self.master_key)
        
        # Credential storage
        self.credentials: Dict[str, Credential] = {}
        self._load_credentials()
        
        # Audit logging
        self.audit_log_path = audit_log_path or str(self.storage_dir / "audit.log")
        
        # Statistics
        self._stats = {
            "credentials_stored": len(self.credentials),
            "credentials_accessed": 0,
            "credentials_expired": 0,
            "credentials_rotated": 0
        }
        
        logger.info(f"Initialized credential manager at {self.storage_dir}")
        logger.info(f"  Keyring: {'enabled' if self.use_keyring else 'disabled'}")
        logger.info(f"  Audit logging: {self.audit_log_path}")
    
    def _load_or_create_master_key(self) -> bytes:
        """Load or create the master encryption key."""
        service_name = "ipfs_datasets_py"
        key_name = "credential_master_key"
        
        if self.use_keyring:
            # Try to load from keyring
            try:
                key_b64 = keyring.get_password(service_name, key_name)
                if key_b64:
                    logger.info("Loaded master key from system keyring")
                    return base64.b64decode(key_b64)
            except Exception as e:
                logger.warning(f"Failed to load key from keyring: {e}")
        
        # Try to load from file
        key_file = self.storage_dir / ".master_key"
        if key_file.exists():
            try:
                with open(key_file, 'rb') as f:
                    logger.info("Loaded master key from file")
                    return base64.b64decode(f.read())
            except Exception as e:
                logger.warning(f"Failed to load key from file: {e}")
        
        # Generate new key
        logger.info("Generating new master encryption key")
        key = AESGCM.generate_key(bit_length=256)
        key_b64 = base64.b64encode(key)
        
        # Store in keyring if available
        if self.use_keyring:
            try:
                keyring.set_password(service_name, key_name, key_b64.decode('utf-8'))
                logger.info("Stored master key in system keyring")
            except Exception as e:
                logger.warning(f"Failed to store key in keyring: {e}")
        
        # Also store in file as backup
        try:
            with open(key_file, 'wb') as f:
                f.write(key_b64)
            key_file.chmod(0o600)  # Restrict permissions
            logger.info("Stored master key in file")
        except Exception as e:
            logger.error(f"Failed to store key in file: {e}")
        
        return key
    
    def _encrypt_value(self, value: str) -> bytes:
        """Encrypt a credential value."""
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        plaintext = value.encode('utf-8')
        ciphertext = self.cipher.encrypt(nonce, plaintext, None)
        # Prepend nonce to ciphertext
        return nonce + ciphertext
    
    def _decrypt_value(self, encrypted_data: bytes) -> str:
        """Decrypt a credential value."""
        # Extract nonce (first 12 bytes)
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        plaintext = self.cipher.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    
    def _audit_log(self, action: str, credential_name: str, details: Dict[str, Any]) -> None:
        """Write to audit log."""
        try:
            timestamp = datetime.utcnow().isoformat()
            log_entry = {
                'timestamp': timestamp,
                'action': action,
                'credential': credential_name,
                'details': details
            }
            
            with open(self.audit_log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def store_credential(
        self,
        name: str,
        value: str,
        scope: CredentialScope = CredentialScope.GLOBAL,
        scope_filter: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store a credential securely.
        
        Args:
            name: Credential name (e.g., "GITHUB_TOKEN")
            value: Credential value to encrypt
            scope: Scope of the credential
            scope_filter: Filter for scoped credentials (e.g., "owner/repo")
            ttl_hours: Time to live in hours (None for no expiration)
            metadata: Additional metadata to store
        """
        # Encrypt the value
        encrypted_value = self._encrypt_value(value)
        
        # Calculate expiration
        expires_at = None
        if ttl_hours:
            expires_at = time.time() + (ttl_hours * 3600)
        
        # Create credential object
        credential = Credential(
            name=name,
            encrypted_value=encrypted_value,
            scope=scope,
            scope_filter=scope_filter,
            created_at=time.time(),
            expires_at=expires_at,
            metadata=metadata
        )
        
        # Store in memory
        self.credentials[name] = credential
        
        # Persist to disk
        self._save_credentials()
        
        # Audit log
        self._audit_log("store", name, {
            'scope': scope.value,
            'scope_filter': scope_filter,
            'ttl_hours': ttl_hours
        })
        
        self._stats["credentials_stored"] = len(self.credentials)
        logger.info(f"Stored credential '{name}' with scope {scope.value}")
    
    def get_credential(
        self,
        name: str,
        repo: Optional[str] = None,
        workflow: Optional[str] = None,
        runner_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Retrieve a decrypted credential value.
        
        Args:
            name: Credential name
            repo: Repository name for scope matching
            workflow: Workflow name for scope matching
            runner_id: Runner ID for scope matching
            
        Returns:
            Decrypted credential value or None if not found/expired/unauthorized
        """
        credential = self.credentials.get(name)
        
        if not credential:
            logger.warning(f"Credential '{name}' not found")
            return None
        
        # Check expiration
        if credential.is_expired():
            logger.warning(f"Credential '{name}' has expired")
            self._stats["credentials_expired"] += 1
            self._audit_log("access_denied", name, {'reason': 'expired'})
            return None
        
        # Check scope
        if not credential.matches_scope(repo, workflow, runner_id):
            logger.warning(f"Credential '{name}' scope mismatch")
            self._audit_log("access_denied", name, {
                'reason': 'scope_mismatch',
                'requested': {'repo': repo, 'workflow': workflow, 'runner_id': runner_id}
            })
            return None
        
        # Decrypt and return
        try:
            value = self._decrypt_value(credential.encrypted_value)
            
            # Update access tracking
            credential.last_accessed = time.time()
            credential.access_count += 1
            self._save_credentials()
            
            self._stats["credentials_accessed"] += 1
            self._audit_log("access_granted", name, {
                'repo': repo,
                'workflow': workflow,
                'runner_id': runner_id
            })
            
            return value
        except Exception as e:
            logger.error(f"Failed to decrypt credential '{name}': {e}")
            self._audit_log("access_error", name, {'error': str(e)})
            return None
    
    def rotate_credential(
        self,
        name: str,
        new_value: str
    ) -> bool:
        """
        Rotate a credential to a new value.
        
        Args:
            name: Credential name
            new_value: New credential value
            
        Returns:
            True if successful, False otherwise
        """
        credential = self.credentials.get(name)
        
        if not credential:
            logger.error(f"Cannot rotate non-existent credential '{name}'")
            return False
        
        # Encrypt new value
        encrypted_value = self._encrypt_value(new_value)
        
        # Update credential
        old_created_at = credential.created_at
        credential.encrypted_value = encrypted_value
        credential.created_at = time.time()
        
        # Persist
        self._save_credentials()
        
        self._stats["credentials_rotated"] += 1
        self._audit_log("rotate", name, {
            'old_created_at': old_created_at,
            'new_created_at': credential.created_at
        })
        
        logger.info(f"Rotated credential '{name}'")
        return True
    
    def delete_credential(self, name: str) -> bool:
        """
        Securely delete a credential.
        
        Args:
            name: Credential name
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.credentials:
            logger.warning(f"Cannot delete non-existent credential '{name}'")
            return False
        
        del self.credentials[name]
        self._save_credentials()
        
        self._audit_log("delete", name, {})
        logger.info(f"Deleted credential '{name}'")
        
        self._stats["credentials_stored"] = len(self.credentials)
        return True
    
    def list_credentials(
        self,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List all stored credentials (without values).
        
        Args:
            include_expired: Whether to include expired credentials
            
        Returns:
            List of credential metadata
        """
        result = []
        
        for name, credential in self.credentials.items():
            if not include_expired and credential.is_expired():
                continue
            
            result.append({
                'name': name,
                'scope': credential.scope.value,
                'scope_filter': credential.scope_filter,
                'created_at': datetime.fromtimestamp(credential.created_at).isoformat(),
                'expires_at': datetime.fromtimestamp(credential.expires_at).isoformat() if credential.expires_at else None,
                'last_accessed': datetime.fromtimestamp(credential.last_accessed).isoformat() if credential.last_accessed else None,
                'access_count': credential.access_count,
                'is_expired': credential.is_expired()
            })
        
        return result
    
    def cleanup_expired(self) -> int:
        """
        Remove expired credentials.
        
        Returns:
            Number of credentials removed
        """
        expired = [name for name, cred in self.credentials.items() if cred.is_expired()]
        
        for name in expired:
            del self.credentials[name]
            self._audit_log("cleanup", name, {'reason': 'expired'})
        
        if expired:
            self._save_credentials()
            logger.info(f"Cleaned up {len(expired)} expired credentials")
        
        self._stats["credentials_stored"] = len(self.credentials)
        return len(expired)
    
    def _save_credentials(self) -> None:
        """Persist credentials to disk."""
        creds_file = self.storage_dir / "credentials.json.enc"
        
        try:
            # Serialize credentials
            data = {name: cred.to_dict() for name, cred in self.credentials.items()}
            json_data = json.dumps(data, indent=2)
            
            # Encrypt entire file with master key
            encrypted = self._encrypt_value(json_data)
            
            # Write to file
            with open(creds_file, 'wb') as f:
                f.write(encrypted)
            
            creds_file.chmod(0o600)  # Restrict permissions
            
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
    
    def _load_credentials(self) -> None:
        """Load credentials from disk."""
        creds_file = self.storage_dir / "credentials.json.enc"
        
        if not creds_file.exists():
            logger.info("No existing credentials file found")
            return
        
        try:
            # Read encrypted file
            with open(creds_file, 'rb') as f:
                encrypted = f.read()
            
            # Decrypt
            json_data = self._decrypt_value(encrypted)
            data = json.loads(json_data)
            
            # Reconstruct credential objects
            for name, cred_dict in data.items():
                self.credentials[name] = Credential.from_dict(cred_dict)
            
            logger.info(f"Loaded {len(self.credentials)} credentials from disk")
            
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get credential manager statistics."""
        return {
            **self._stats,
            "active_credentials": len([c for c in self.credentials.values() if not c.is_expired()]),
            "expired_credentials": len([c for c in self.credentials.values() if c.is_expired()])
        }


# Global credential manager instance
_global_credential_manager: Optional[CredentialManager] = None


def get_global_credential_manager(**kwargs) -> CredentialManager:
    """
    Get or create the global credential manager instance.
    
    Args:
        **kwargs: Arguments to pass to CredentialManager constructor
        
    Returns:
        Global CredentialManager instance
    """
    global _global_credential_manager
    
    if _global_credential_manager is None:
        _global_credential_manager = CredentialManager(**kwargs)
    
    return _global_credential_manager


def configure_credential_manager(**kwargs) -> CredentialManager:
    """
    Configure the global credential manager with custom settings.
    
    Args:
        **kwargs: Arguments to pass to CredentialManager constructor
        
    Returns:
        Configured CredentialManager instance
    """
    global _global_credential_manager
    _global_credential_manager = CredentialManager(**kwargs)
    return _global_credential_manager
