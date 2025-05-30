"""
Security and Governance Module for IPFS Datasets.

This module provides security features for the IPFS Datasets Python library, including:
- Encryption and decryption of sensitive data
- Access control mechanisms
- Data provenance tracking
- Audit logging for data operations
- Key management and rotation
- Policy enforcement
- Capability-based authorization using UCAN (User Controlled Authorization Networks)

The UCAN integration enables:
- Capability-based access control for encryption keys
- Secure delegation of encryption/decryption permissions
- Fine-grained access control with caveats
- Revocation of previously granted capabilities
- Content-addressed authorization via DIDs (Decentralized Identifiers)
"""

import os
import io
import time
import uuid
import json
import base64
import hashlib
import logging
import datetime
from typing import Dict, List, Any, Optional, Union, Callable, Tuple, BinaryIO
from dataclasses import dataclass, field, asdict
from functools import wraps
import contextlib
import threading
from pathlib import Path

# For encryption
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes, hmac, padding
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, load_pem_public_key,
        Encoding, PrivateFormat, PublicFormat, NoEncryption
    )
    from cryptography.hazmat.backends import default_backend
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

# For secure storage
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

# Import monitoring system for audit logging
try:
    from ipfs_datasets_py.monitoring import get_logger, get_metrics_registry
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False

# Import UCAN module for capability-based authorization
try:
    from ipfs_datasets_py.ucan import (
        initialize_ucan, get_ucan_manager, UCANCapability, UCANToken, UCANKeyPair
    )
    UCAN_AVAILABLE = True
except ImportError:
    UCAN_AVAILABLE = False


# Constants
DEFAULT_SECURITY_DIR = os.path.expanduser("~/.ipfs_datasets/security")
KEY_SIZES = {
    "AES-128": 16,  # 128 bits
    "AES-192": 24,  # 192 bits
    "AES-256": 32,  # 256 bits
}
DEFAULT_ENCRYPTION_ALGORITHM = "AES-256"
DEFAULT_KDF_ITERATIONS = 100000
DEFAULT_SALT_SIZE = 16  # bytes
DEFAULT_IV_SIZE = 16  # bytes for AES
DEFAULT_PBKDF2_HASH = "SHA-256"
RSA_KEY_SIZE = 2048
RSA_PUBLIC_EXPONENT = 65537
ACCESS_LEVELS = ["read", "write", "admin"]


@dataclass
class SecurityConfig:
    """Configuration for security features."""
    enabled: bool = True
    security_dir: str = DEFAULT_SECURITY_DIR
    encryption_algorithm: str = DEFAULT_ENCRYPTION_ALGORITHM
    kdf_iterations: int = DEFAULT_KDF_ITERATIONS
    pbkdf2_hash: str = DEFAULT_PBKDF2_HASH
    require_authentication: bool = False
    log_all_access: bool = True
    track_provenance: bool = True
    audit_log_path: Optional[str] = None
    use_system_keyring: bool = KEYRING_AVAILABLE
    use_ucan: bool = UCAN_AVAILABLE
    default_capability_ttl: int = 3600


@dataclass
class UserCredentials:
    """User credentials and permissions."""
    username: str
    # Password hash is stored as a secure hash, not plaintext
    password_hash: str
    salt: str
    access_level: str = "read"  # read, write, admin
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    last_login: Optional[str] = None
    permissions: Dict[str, List[str]] = field(default_factory=dict)
    groups: List[str] = field(default_factory=list)


@dataclass
class EncryptionKey:
    """Encryption key with metadata."""
    key_id: str
    algorithm: str
    key_material: bytes
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    expires_at: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    ucan_did: Optional[str] = None  # DID for UCAN capabilities


@dataclass
class ResourcePolicy:
    """Access policy for a resource."""
    resource_id: str
    resource_type: str
    owner: str
    allowed_users: List[str]
    allowed_groups: List[str]
    read_access: List[str]
    write_access: List[str]
    admin_access: List[str]
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())


@dataclass
class ProcessStep:
    """A single processing step in a data transformation pipeline."""
    step_id: str
    operation: str  # Type of operation (e.g., "filter", "transform", "join")
    description: str  # Human-readable description
    tool: str  # Tool/library used (e.g., "duckdb", "arrow", "custom")
    parameters: Dict[str, Any]  # Parameters used for the operation
    start_time: str
    end_time: Optional[str] = None
    status: str = "running"  # running, completed, failed
    error: Optional[str] = None  # Error message if status is failed
    inputs: List[str] = field(default_factory=list)  # Input data identifiers
    outputs: List[str] = field(default_factory=list)  # Output data identifiers
    metrics: Dict[str, Any] = field(default_factory=dict)  # Performance metrics
    environment: Dict[str, Any] = field(default_factory=dict)  # Execution environment details
    operator: Optional[str] = None  # User or system component that executed the step

@dataclass
class DataLineage:
    """Detailed lineage information tracking data through its lifecycle."""
    source_system: str  # Original system/location the data came from
    source_type: str  # Type of source (e.g., "database", "file", "api")
    extraction_method: str  # How the data was extracted
    extraction_time: str  # When the data was extracted
    transformations: List[str] = field(default_factory=list)  # IDs of process steps
    derived_datasets: List[str] = field(default_factory=list)  # Datasets derived from this one
    upstream_datasets: List[str] = field(default_factory=list)  # Datasets this one derives from
    lineage_graph: Dict[str, List[str]] = field(default_factory=dict)  # Graph representation of lineage
    versioning: Dict[str, Any] = field(default_factory=dict)  # Version control information
    quality_metrics: Dict[str, Any] = field(default_factory=dict)  # Data quality metrics

@dataclass
class DataProvenance:
    """Comprehensive provenance information for a piece of data."""
    data_id: str  # Unique identifier for the data
    source: str  # Source of the data
    creator: str  # User or system that created the data
    creation_time: str  # When the data was created
    process_steps: List[Dict[str, Any]]  # Processing steps that led to this data
    parent_ids: List[str]  # Parent data IDs
    version: str  # Version of the data
    checksum: str  # Checksum/hash of the data for verification
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata

    # Enhanced fields for detailed tracking
    data_type: str = "unknown"  # Type of data (e.g., "dataset", "model", "index", "embedding")
    schema: Optional[Dict[str, Any]] = None  # Data schema if applicable
    size_bytes: Optional[int] = None  # Size of the data in bytes
    record_count: Optional[int] = None  # Number of records if applicable
    content_type: Optional[str] = None  # MIME type or format
    retention_policy: Optional[str] = None  # Data retention policy
    lineage: Optional[DataLineage] = None  # Detailed lineage information
    access_history: List[Dict[str, Any]] = field(default_factory=list)  # History of data access
    transformation_history: List[ProcessStep] = field(default_factory=list)  # Detailed transformation steps
    data_flow: Dict[str, List[str]] = field(default_factory=dict)  # Data flow graph
    tags: List[str] = field(default_factory=list)  # Tags for categorization
    external_references: Dict[str, str] = field(default_factory=dict)  # External system references
    compliance: Dict[str, Any] = field(default_factory=dict)  # Compliance information
    verification_status: str = "unverified"  # Verification status of the data


@dataclass
class AuditLogEntry:
    """Audit log entry for security-related events."""
    event_id: str
    timestamp: str
    event_type: str
    user: str
    resource_id: Optional[str]
    resource_type: Optional[str]
    action: str
    status: str
    details: Dict[str, Any]
    source_ip: Optional[str] = None
    success: bool = True


class SecurityManager:
    """Main class for security and governance features."""

    _instance = None

    @classmethod
    def get_instance(cls) -> 'SecurityManager':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls, config: Optional[SecurityConfig] = None) -> 'SecurityManager':
        """
        Initialize the security manager.

        Args:
            config: Configuration for security features

        Returns:
            SecurityManager: The initialized security manager
        """
        instance = cls.get_instance()
        instance.configure(config or SecurityConfig())
        return instance

    def __init__(self):
        """Initialize the security manager."""
        self.config = SecurityConfig()
        self.logger = logging.getLogger(__name__)
        self.initialized = False
        self.current_user = None
        self.encryption_keys = {}
        self.users = {}
        self.policies = {}
        self.provenance_cache = {}
        self._lock = threading.RLock()
        self.ucan_manager = None

        # Initialize security directory
        if not os.path.exists(DEFAULT_SECURITY_DIR):
            os.makedirs(DEFAULT_SECURITY_DIR, exist_ok=True)

    def configure(self, config: SecurityConfig) -> None:
        """
        Configure the security manager.

        Args:
            config: Configuration for security features
        """
        self.config = config

        # Set up logger if monitoring is available
        if MONITORING_AVAILABLE:
            self.logger = get_logger("security")
        else:
            # Set up basic logger
            self.logger = logging.getLogger(__name__)
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)

        # Create security directory if needed
        if not os.path.exists(config.security_dir):
            os.makedirs(config.security_dir, exist_ok=True)

        # Initialize audit log file if specified
        if config.audit_log_path:
            audit_log_dir = os.path.dirname(config.audit_log_path)
            if not os.path.exists(audit_log_dir):
                os.makedirs(audit_log_dir, exist_ok=True)

        # Initialize UCAN if enabled
        if config.use_ucan and UCAN_AVAILABLE:
            try:
                self.ucan_manager = initialize_ucan()
                self.logger.info("UCAN manager initialized")
            except Exception as e:
                self.logger.error(f"Error initializing UCAN manager: {str(e)}")
                self.config.use_ucan = False

        # Load existing users if available
        self._load_users()

        # Load existing encryption keys if available
        self._load_encryption_keys()

        # Load resource policies if available
        self._load_policies()

        self.initialized = True
        self.logger.info("Security manager initialized")

    def _load_users(self) -> None:
        """Load users from storage."""
        users_file = os.path.join(self.config.security_dir, "users.json")
        if os.path.exists(users_file):
            try:
                with open(users_file, 'r') as f:
                    user_data = json.load(f)

                self.users = {}
                for username, data in user_data.items():
                    self.users[username] = UserCredentials(
                        username=username,
                        password_hash=data["password_hash"],
                        salt=data["salt"],
                        access_level=data["access_level"],
                        created_at=data.get("created_at", datetime.datetime.now().isoformat()),
                        last_login=data.get("last_login"),
                        permissions=data.get("permissions", {}),
                        groups=data.get("groups", [])
                    )

                self.logger.info(f"Loaded {len(self.users)} users from storage")
            except Exception as e:
                self.logger.error(f"Error loading users: {str(e)}")

    def _save_users(self) -> None:
        """Save users to storage."""
        users_file = os.path.join(self.config.security_dir, "users.json")
        try:
            # Convert users to dictionary for serialization
            user_data = {}
            for username, user in self.users.items():
                user_data[username] = {
                    "password_hash": user.password_hash,
                    "salt": user.salt,
                    "access_level": user.access_level,
                    "created_at": user.created_at,
                    "last_login": user.last_login,
                    "permissions": user.permissions,
                    "groups": user.groups
                }

            with open(users_file, 'w') as f:
                json.dump(user_data, f, indent=2)

            self.logger.debug(f"Saved {len(self.users)} users to storage")
        except Exception as e:
            self.logger.error(f"Error saving users: {str(e)}")

    def _load_encryption_keys(self) -> None:
        """Load encryption keys from storage."""
        # In a real implementation, we would use a more secure storage method
        # This is just for demonstration purposes
        keys_file = os.path.join(self.config.security_dir, "encryption_keys.json")
        if os.path.exists(keys_file):
            try:
                with open(keys_file, 'r') as f:
                    keys_data = json.load(f)

                self.encryption_keys = {}
                for key_id, data in keys_data.items():
                    self.encryption_keys[key_id] = EncryptionKey(
                        key_id=key_id,
                        algorithm=data["algorithm"],
                        key_material=base64.b64decode(data["key_material"]),
                        created_at=data.get("created_at", datetime.datetime.now().isoformat()),
                        expires_at=data.get("expires_at"),
                        context=data.get("context", {})
                    )

                self.logger.info(f"Loaded {len(self.encryption_keys)} encryption keys from storage")
            except Exception as e:
                self.logger.error(f"Error loading encryption keys: {str(e)}")

    def _save_encryption_keys(self) -> None:
        """Save encryption keys to storage."""
        # In a real implementation, we would use a more secure storage method
        # This is just for demonstration purposes
        keys_file = os.path.join(self.config.security_dir, "encryption_keys.json")
        try:
            # Convert keys to dictionary for serialization
            keys_data = {}
            for key_id, key in self.encryption_keys.items():
                keys_data[key_id] = {
                    "algorithm": key.algorithm,
                    "key_material": base64.b64encode(key.key_material).decode(),
                    "created_at": key.created_at,
                    "expires_at": key.expires_at,
                    "context": key.context
                }

            with open(keys_file, 'w') as f:
                json.dump(keys_data, f, indent=2)

            self.logger.debug(f"Saved {len(self.encryption_keys)} encryption keys to storage")
        except Exception as e:
            self.logger.error(f"Error saving encryption keys: {str(e)}")

    def _load_policies(self) -> None:
        """Load resource policies from storage."""
        policies_file = os.path.join(self.config.security_dir, "policies.json")
        if os.path.exists(policies_file):
            try:
                with open(policies_file, 'r') as f:
                    policies_data = json.load(f)

                self.policies = {}
                for resource_id, data in policies_data.items():
                    self.policies[resource_id] = ResourcePolicy(
                        resource_id=resource_id,
                        resource_type=data["resource_type"],
                        owner=data["owner"],
                        allowed_users=data["allowed_users"],
                        allowed_groups=data["allowed_groups"],
                        read_access=data["read_access"],
                        write_access=data["write_access"],
                        admin_access=data["admin_access"],
                        created_at=data.get("created_at", datetime.datetime.now().isoformat()),
                        modified_at=data.get("modified_at", datetime.datetime.now().isoformat())
                    )

                self.logger.info(f"Loaded {len(self.policies)} resource policies from storage")
            except Exception as e:
                self.logger.error(f"Error loading resource policies: {str(e)}")

    def _save_policies(self) -> None:
        """Save resource policies to storage."""
        policies_file = os.path.join(self.config.security_dir, "policies.json")
        try:
            # Convert policies to dictionary for serialization
            policies_data = {}
            for resource_id, policy in self.policies.items():
                policies_data[resource_id] = asdict(policy)

            with open(policies_file, 'w') as f:
                json.dump(policies_data, f, indent=2)

            self.logger.debug(f"Saved {len(self.policies)} resource policies to storage")
        except Exception as e:
            self.logger.error(f"Error saving resource policies: {str(e)}")

    def create_user(self, username: str, password: str, access_level: str = "read") -> bool:
        """
        Create a new user.

        Args:
            username: Username for the new user
            password: Password for the new user
            access_level: Access level (read, write, admin)

        Returns:
            bool: Whether the user was created successfully
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return False

        if access_level not in ACCESS_LEVELS:
            self.logger.error(f"Invalid access level: {access_level}")
            return False

        with self._lock:
            # Check if user already exists
            if username in self.users:
                self.logger.warning(f"User {username} already exists")
                return False

            # Generate salt
            salt = os.urandom(DEFAULT_SALT_SIZE)
            salt_b64 = base64.b64encode(salt).decode()

            # Hash password
            password_hash = self._hash_password(password, salt)

            # Create user
            user = UserCredentials(
                username=username,
                password_hash=password_hash,
                salt=salt_b64,
                access_level=access_level
            )

            # Store user
            self.users[username] = user

            # Save users to storage
            self._save_users()

            # Log audit event
            self._log_audit_event(
                event_type="user_created",
                user="system",
                action="create_user",
                resource_id=username,
                resource_type="user",
                details={"access_level": access_level}
            )

            self.logger.info(f"Created user {username} with access level {access_level}")
            return True

    def authenticate_user(self, username: str, password: str) -> bool:
        """
        Authenticate a user.

        Args:
            username: Username to authenticate
            password: Password to authenticate

        Returns:
            bool: Whether authentication was successful
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return False

        with self._lock:
            # Check if user exists
            if username not in self.users:
                self.logger.warning(f"User {username} does not exist")
                self._log_audit_event(
                    event_type="authentication_failure",
                    user=username,
                    action="authenticate",
                    details={"reason": "user_not_found"},
                    success=False
                )
                return False

            user = self.users[username]

            # Get salt
            salt = base64.b64decode(user.salt)

            # Hash password
            password_hash = self._hash_password(password, salt)

            # Check password
            if password_hash != user.password_hash:
                self.logger.warning(f"Invalid password for user {username}")
                self._log_audit_event(
                    event_type="authentication_failure",
                    user=username,
                    action="authenticate",
                    details={"reason": "invalid_password"},
                    success=False
                )
                return False

            # Update last login
            user.last_login = datetime.datetime.now().isoformat()
            self._save_users()

            # Set current user
            self.current_user = username

            # Log audit event
            self._log_audit_event(
                event_type="authentication_success",
                user=username,
                action="authenticate",
                details={"last_login": user.last_login}
            )

            self.logger.info(f"User {username} authenticated successfully")
            return True

    def _hash_password(self, password: str, salt: bytes) -> str:
        """
        Hash a password using PBKDF2.

        Args:
            password: Password to hash
            salt: Salt for the hash

        Returns:
            str: Base64-encoded password hash
        """
        # Create PBKDF2 hasher
        kdf = PBKDF2HMAC(
            algorithm=getattr(hashes, self.config.pbkdf2_hash.replace("-", ""))(),
            length=32,  # 256 bits
            salt=salt,
            iterations=self.config.kdf_iterations,
            backend=default_backend()
        )

        # Hash password
        password_hash = kdf.derive(password.encode())

        # Convert to base64
        return base64.b64encode(password_hash).decode()

    def generate_encryption_key(self, algorithm: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
                            with_ucan: bool = True) -> str:
        """
        Generate a new encryption key.

        Args:
            algorithm: Encryption algorithm to use
            context: Context for the key
            with_ucan: Whether to create UCAN capabilities for this key

        Returns:
            str: Key ID for the generated key
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return ""

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return ""

        algorithm = algorithm or self.config.encryption_algorithm
        if algorithm not in KEY_SIZES:
            self.logger.error(f"Invalid encryption algorithm: {algorithm}")
            return ""

        with self._lock:
            # Generate key ID
            key_id = str(uuid.uuid4())

            # Generate key material
            key_size = KEY_SIZES[algorithm]
            key_material = os.urandom(key_size)

            # Initialize context if not provided
            actual_context = context or {}

            # Generate UCAN DID for the key if enabled
            ucan_did = None
            if self.config.use_ucan and UCAN_AVAILABLE and with_ucan and self.ucan_manager:
                try:
                    # Generate a keypair for this encryption key
                    ucan_keypair = self.ucan_manager.generate_keypair()
                    ucan_did = ucan_keypair.did

                    # Create self-issued capability tokens for this key
                    self._create_key_capabilities(ucan_did, key_id)

                    # Add UCAN info to context
                    actual_context["ucan_enabled"] = True
                    self.logger.info(f"Created UCAN capabilities for key {key_id} with DID {ucan_did}")
                except Exception as e:
                    self.logger.error(f"Error creating UCAN capabilities for key {key_id}: {str(e)}")

            # Create key
            key = EncryptionKey(
                key_id=key_id,
                algorithm=algorithm,
                key_material=key_material,
                context=actual_context,
                ucan_did=ucan_did
            )

            # Store key
            self.encryption_keys[key_id] = key

            # Save keys to storage
            self._save_encryption_keys()

            # Log audit event
            self._log_audit_event(
                event_type="key_generated",
                user=self.current_user or "system",
                action="generate_key",
                resource_id=key_id,
                resource_type="encryption_key",
                details={
                    "algorithm": algorithm,
                    "ucan_enabled": ucan_did is not None
                }
            )

            self.logger.info(f"Generated encryption key {key_id} using algorithm {algorithm}")
            return key_id

    def _create_key_capabilities(self, did: str, key_id: str) -> None:
        """
        Create initial UCAN capabilities for a key.

        This method creates self-issued capabilities for a key's DID, granting it
        full rights over the key including encryption, decryption, delegation and revocation.
        These self-issued capabilities are the foundation for the capability delegation system.

        Args:
            did: DID to grant capabilities to
            key_id: Encryption key ID
        """
        if not self.ucan_manager:
            return

        # Create self-issued capabilities for all operations on this key
        capabilities = []

        for action in ["encrypt", "decrypt", "delegate", "revoke"]:
            capabilities.append(UCANCapability(
                resource=key_id,
                action=action
            ))

        # Create token with these capabilities
        # Since this is self-issued, the issuer and audience are the same
        try:
            token = self.ucan_manager.create_token(
                issuer_did=did,
                audience_did=did,
                capabilities=capabilities,
                ttl=self.config.default_capability_ttl * 24 * 365  # Long-lived (1 year)
            )
            self.logger.debug(f"Created self-issued UCAN token {token.token_id} for key {key_id}")
        except Exception as e:
            self.logger.error(f"Error creating UCAN token for key {key_id}: {str(e)}")

    def encrypt_data(self, data: Union[bytes, str], key_id: Optional[str] = None,
                    requestor_did: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
        """
        Encrypt data using a specified key or a new key.

        This method encrypts data using AES encryption with the specified key.
        If UCAN is enabled and a requestor_did is provided, it performs capability-based
        authorization to ensure the requestor has encryption rights for the key.

        The encryption process:
        1. If no key is provided, generates a new encryption key
        2. If UCAN is enabled, validates the requestor has 'encrypt' capability for the key
        3. Performs AES encryption with CBC mode and PKCS7 padding
        4. Returns both the encrypted data and metadata about the encryption

        Args:
            data: Data to encrypt (bytes or string)
            key_id: ID of the key to use, or None to generate a new key
            requestor_did: DID of the requestor (for UCAN capability checks)

        Returns:
            tuple: (encrypted_data, metadata) where metadata contains information about the
                  encryption algorithm, key ID, and UCAN details if applicable
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return b"", {}

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return b"", {}

        # Convert string to bytes if needed
        if isinstance(data, str):
            data = data.encode()

        with self._lock:
            # Get or generate key
            if key_id is None:
                key_id = self.generate_encryption_key()

            if key_id not in self.encryption_keys:
                self.logger.error(f"Encryption key {key_id} not found")
                return b"", {}

            key = self.encryption_keys[key_id]

            # Check UCAN capability if enabled and a requestor DID is provided
            if self.config.use_ucan and UCAN_AVAILABLE and self.ucan_manager and requestor_did:
                if not self._check_key_capability(requestor_did, key_id, "encrypt"):
                    self.logger.error(f"DID {requestor_did} does not have encrypt capability for key {key_id}")
                    return b"", {}

            # Generate IV
            iv = os.urandom(DEFAULT_IV_SIZE)

            # Create cipher
            cipher = Cipher(
                algorithms.AES(key.key_material),
                modes.CBC(iv),
                backend=default_backend()
            )

            # Create encryptor
            encryptor = cipher.encryptor()

            # Apply padding
            padder = padding.PKCS7(algorithms.AES.block_size).padder()
            padded_data = padder.update(data) + padder.finalize()

            # Encrypt data
            encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

            # Combine IV and encrypted data
            result = iv + encrypted_data

            # Create metadata
            metadata = {
                "algorithm": key.algorithm,
                "key_id": key_id,
                "iv": base64.b64encode(iv).decode(),
                "encryption_time": datetime.datetime.now().isoformat()
            }

            # Add UCAN info to metadata if applicable
            if requestor_did and key.ucan_did:
                metadata["ucan"] = {
                    "requestor": requestor_did,
                    "key_did": key.ucan_did
                }

            # Log audit event
            self._log_audit_event(
                event_type="data_encrypted",
                user=self.current_user or "system",
                action="encrypt_data",
                resource_id=key_id,
                resource_type="encryption_key",
                details={
                    "data_size": len(data),
                    "algorithm": key.algorithm,
                    "ucan_requestor": requestor_did
                }
            )

            self.logger.debug(f"Encrypted {len(data)} bytes using key {key_id}")
            return result, metadata

    def _check_key_capability(self, did: str, key_id: str, action: str) -> bool:
        """
        Check if a DID has a capability for an encryption key.

        This method verifies whether a specific DID has been granted a capability
        on an encryption key. It checks all valid UCAN tokens where the DID is
        the audience and verifies that they include the specified capability.

        Capability validation includes checking:
        1. Token validity (not expired, not revoked)
        2. Proper delegation chain (proof tokens)
        3. Action matching (encrypt, decrypt, delegate, etc.)
        4. Resource matching (key_id)
        5. Caveats on the capability (if any)

        Args:
            did: DID to check
            key_id: Encryption key ID
            action: Capability action to check (encrypt, decrypt, delegate, etc.)

        Returns:
            bool: Whether the DID has the capability
        """
        if not self.ucan_manager:
            return False

        try:
            return self.ucan_manager.has_capability(did, key_id, action)
        except Exception as e:
            self.logger.error(f"Error checking capability: {str(e)}")
            return False

    def decrypt_data(self, encrypted_data: bytes, key_id: str, requestor_did: Optional[str] = None) -> bytes:
        """
        Decrypt data using a specified key.

        This method decrypts data that was previously encrypted using the specified key.
        If UCAN is enabled and a requestor_did is provided, it performs capability-based
        authorization to ensure the requestor has decryption rights for the key.

        The decryption process:
        1. Retrieves the specified encryption key
        2. If UCAN is enabled, validates the requestor has 'decrypt' capability for the key
        3. Extracts the initialization vector (IV) from the encrypted data
        4. Performs AES decryption with CBC mode and removes PKCS7 padding
        5. Returns the decrypted data

        Args:
            encrypted_data: Data to decrypt (including IV as a prefix)
            key_id: ID of the key to use
            requestor_did: DID of the requestor (for UCAN capability checks)

        Returns:
            bytes: Decrypted data
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return b""

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return b""

        with self._lock:
            # Get key
            if key_id not in self.encryption_keys:
                self.logger.error(f"Encryption key {key_id} not found")
                return b""

            key = self.encryption_keys[key_id]

            # Check UCAN capability if enabled and a requestor DID is provided
            if self.config.use_ucan and UCAN_AVAILABLE and self.ucan_manager and requestor_did:
                if not self._check_key_capability(requestor_did, key_id, "decrypt"):
                    self.logger.error(f"DID {requestor_did} does not have decrypt capability for key {key_id}")
                    return b""

            # Extract IV
            iv = encrypted_data[:DEFAULT_IV_SIZE]
            actual_encrypted_data = encrypted_data[DEFAULT_IV_SIZE:]

            # Create cipher
            cipher = Cipher(
                algorithms.AES(key.key_material),
                modes.CBC(iv),
                backend=default_backend()
            )

            # Create decryptor
            decryptor = cipher.decryptor()

            # Decrypt data
            padded_data = decryptor.update(actual_encrypted_data) + decryptor.finalize()

            # Remove padding
            unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
            data = unpadder.update(padded_data) + unpadder.finalize()

            # Log audit event
            self._log_audit_event(
                event_type="data_decrypted",
                user=self.current_user or "system",
                action="decrypt_data",
                resource_id=key_id,
                resource_type="encryption_key",
                details={
                    "data_size": len(actual_encrypted_data),
                    "ucan_requestor": requestor_did
                }
            )

            self.logger.debug(f"Decrypted {len(actual_encrypted_data)} bytes using key {key_id}")
            return data

    def encrypt_file(self, input_file: Union[str, BinaryIO], output_file: Union[str, BinaryIO],
                   key_id: Optional[str] = None, requestor_did: Optional[str] = None) -> Dict[str, Any]:
        """
        Encrypt a file using a specified key or a new key.

        Args:
            input_file: Path to input file or file-like object
            output_file: Path to output file or file-like object
            key_id: ID of the key to use, or None to generate a new key
            requestor_did: DID of the requestor (for UCAN capability checks)

        Returns:
            dict: Encryption metadata
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return {}

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return {}

        # Ensure we have file objects
        input_file_obj = input_file if hasattr(input_file, 'read') else open(input_file, 'rb')
        output_file_obj = output_file if hasattr(output_file, 'write') else open(output_file, 'wb')

        try:
            # Read input file
            data = input_file_obj.read()

            # Encrypt data
            encrypted_data, metadata = self.encrypt_data(data, key_id, requestor_did)

            # Write to output file
            output_file_obj.write(encrypted_data)

            return metadata

        finally:
            # Close files if we opened them
            if input_file_obj is not input_file:
                input_file_obj.close()

            if output_file_obj is not output_file:
                output_file_obj.close()

    def decrypt_file(self, input_file: Union[str, BinaryIO], output_file: Union[str, BinaryIO],
                   key_id: str, requestor_did: Optional[str] = None) -> bool:
        """
        Decrypt a file using a specified key.

        Args:
            input_file: Path to input file or file-like object
            output_file: Path to output file or file-like object
            key_id: ID of the key to use
            requestor_did: DID of the requestor (for UCAN capability checks)

        Returns:
            bool: Whether decryption was successful
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not CRYPTOGRAPHY_AVAILABLE:
            self.logger.error("Cryptography module not available")
            return False

        # Ensure we have file objects
        input_file_obj = input_file if hasattr(input_file, 'read') else open(input_file, 'rb')
        output_file_obj = output_file if hasattr(output_file, 'write') else open(output_file, 'wb')

        try:
            # Read input file
            encrypted_data = input_file_obj.read()

            # Decrypt data
            decrypted_data = self.decrypt_data(encrypted_data, key_id, requestor_did)

            # Write to output file
            output_file_obj.write(decrypted_data)

            return True

        except Exception as e:
            self.logger.error(f"Error decrypting file: {str(e)}")
            return False

        finally:
            # Close files if we opened them
            if input_file_obj is not input_file:
                input_file_obj.close()

            if output_file_obj is not output_file:
                output_file_obj.close()

    def create_resource_policy(self, resource_id: str, resource_type: str,
                             owner: Optional[str] = None) -> ResourcePolicy:
        """
        Create a new resource access policy.

        Args:
            resource_id: ID of the resource
            resource_type: Type of the resource
            owner: Owner of the resource (defaults to current user)

        Returns:
            ResourcePolicy: The created policy
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return None

        with self._lock:
            # Set owner to current user if not specified
            actual_owner = owner or self.current_user or "system"

            # Create policy
            policy = ResourcePolicy(
                resource_id=resource_id,
                resource_type=resource_type,
                owner=actual_owner,
                allowed_users=[actual_owner],
                allowed_groups=[],
                read_access=[actual_owner],
                write_access=[actual_owner],
                admin_access=[actual_owner]
            )

            # Store policy
            self.policies[resource_id] = policy

            # Save policies to storage
            self._save_policies()

            # Log audit event
            self._log_audit_event(
                event_type="policy_created",
                user=self.current_user or "system",
                action="create_policy",
                resource_id=resource_id,
                resource_type=resource_type,
                details={"owner": actual_owner}
            )

            self.logger.info(f"Created resource policy for {resource_type} {resource_id} owned by {actual_owner}")
            return policy

    def update_resource_policy(self, resource_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a resource access policy.

        Args:
            resource_id: ID of the resource
            updates: Dictionary of updates to apply

        Returns:
            bool: Whether the update was successful
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        with self._lock:
            # Check if policy exists
            if resource_id not in self.policies:
                self.logger.warning(f"Resource policy for {resource_id} not found")
                return False

            policy = self.policies[resource_id]

            # Check if user has admin access
            current_user = self.current_user or "system"
            if current_user != policy.owner and current_user not in policy.admin_access:
                self.logger.warning(f"User {current_user} does not have admin access to {resource_id}")
                self._log_audit_event(
                    event_type="policy_update_denied",
                    user=current_user,
                    action="update_policy",
                    resource_id=resource_id,
                    resource_type=policy.resource_type,
                    details={"reason": "insufficient_permissions"},
                    success=False
                )
                return False

            # Apply updates
            for key, value in updates.items():
                if hasattr(policy, key):
                    setattr(policy, key, value)

            # Update modification time
            policy.modified_at = datetime.datetime.now().isoformat()

            # Save policies to storage
            self._save_policies()

            # Log audit event
            self._log_audit_event(
                event_type="policy_updated",
                user=current_user,
                action="update_policy",
                resource_id=resource_id,
                resource_type=policy.resource_type,
                details={"updates": updates}
            )

            self.logger.info(f"Updated resource policy for {resource_id}")
            return True

    def check_access(self, resource_id: str, access_type: str) -> bool:
        """
        Check if the current user has access to a resource.

        Args:
            resource_id: ID of the resource
            access_type: Type of access (read, write, admin)

        Returns:
            bool: Whether the user has access
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if access_type not in ["read", "write", "admin"]:
            self.logger.error(f"Invalid access type: {access_type}")
            return False

        with self._lock:
            # Get current user
            current_user = self.current_user
            if not current_user:
                self.logger.warning("No user authenticated")
                return False

            # Check if policy exists
            if resource_id not in self.policies:
                self.logger.warning(f"Resource policy for {resource_id} not found")
                return False

            policy = self.policies[resource_id]

            # Check if user is owner
            if current_user == policy.owner:
                return True

            # Check if user has explicit access
            access_list = getattr(policy, f"{access_type}_access")
            if current_user in access_list:
                return True

            # Check if user's groups have access
            if current_user in self.users:
                user = self.users[current_user]
                for group in user.groups:
                    if group in policy.allowed_groups:
                        return True

            # Log audit event for access denied
            self._log_audit_event(
                event_type="access_denied",
                user=current_user,
                action=f"check_{access_type}_access",
                resource_id=resource_id,
                resource_type=policy.resource_type,
                details={"access_type": access_type},
                success=False
            )

            self.logger.info(f"Access denied for user {current_user} to {access_type} {resource_id}")
            return False

    def record_provenance(self, data_id: str, source: str, process_steps: List[Dict[str, Any]],
                        parent_ids: List[str], checksum: str, metadata: Optional[Dict[str, Any]] = None,
                        data_type: str = "unknown", schema: Optional[Dict[str, Any]] = None,
                        size_bytes: Optional[int] = None, record_count: Optional[int] = None,
                        content_type: Optional[str] = None, lineage_info: Optional[Dict[str, Any]] = None,
                        transformation_history: Optional[List[Dict[str, Any]]] = None,
                        tags: Optional[List[str]] = None) -> DataProvenance:
        """
        Record comprehensive provenance information for a piece of data.

        This method creates a detailed record of data provenance, tracking not just basic
        information but comprehensive details about the data's lifecycle, transformations,
        quality, and lineage. This enhanced provenance tracking enables robust data
        governance, audit compliance, and reproducibility of data transformations.

        Args:
            data_id: Unique identifier for the data
            source: Source of the data
            process_steps: List of processing steps applied to the data
            parent_ids: List of parent data IDs
            checksum: Checksum/hash of the data for verification
            metadata: Additional metadata about the data
            data_type: Type of data (e.g., "dataset", "model", "index", "embedding")
            schema: Data schema if applicable
            size_bytes: Size of the data in bytes
            record_count: Number of records if applicable
            content_type: MIME type or format of the data
            lineage_info: Detailed information about the data's lineage
            transformation_history: Detailed history of transformations applied to the data
            tags: Tags for categorizing the data

        Returns:
            DataProvenance: The comprehensive recorded provenance information
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return None

        if not self.config.track_provenance:
            return None

        with self._lock:
            # Process lineage information if provided
            lineage = None
            if lineage_info:
                lineage = DataLineage(
                    source_system=lineage_info.get("source_system", "unknown"),
                    source_type=lineage_info.get("source_type", "unknown"),
                    extraction_method=lineage_info.get("extraction_method", "unknown"),
                    extraction_time=lineage_info.get("extraction_time", datetime.datetime.now().isoformat()),
                    transformations=lineage_info.get("transformations", []),
                    derived_datasets=lineage_info.get("derived_datasets", []),
                    upstream_datasets=lineage_info.get("upstream_datasets", []),
                    lineage_graph=lineage_info.get("lineage_graph", {}),
                    versioning=lineage_info.get("versioning", {}),
                    quality_metrics=lineage_info.get("quality_metrics", {})
                )

            # Process transformation history if provided
            process_step_objects = []
            if transformation_history:
                for step in transformation_history:
                    process_step_objects.append(ProcessStep(
                        step_id=step.get("step_id", str(uuid.uuid4())),
                        operation=step.get("operation", "unknown"),
                        description=step.get("description", ""),
                        tool=step.get("tool", "unknown"),
                        parameters=step.get("parameters", {}),
                        start_time=step.get("start_time", datetime.datetime.now().isoformat()),
                        end_time=step.get("end_time"),
                        status=step.get("status", "completed"),
                        error=step.get("error"),
                        inputs=step.get("inputs", []),
                        outputs=step.get("outputs", []),
                        metrics=step.get("metrics", {}),
                        environment=step.get("environment", {}),
                        operator=step.get("operator", self.current_user or "system")
                    ))

            # Create comprehensive provenance record
            provenance = DataProvenance(
                data_id=data_id,
                source=source,
                creator=self.current_user or "system",
                creation_time=datetime.datetime.now().isoformat(),
                process_steps=process_steps,
                parent_ids=parent_ids,
                version="1.0",
                checksum=checksum,
                metadata=metadata or {},
                data_type=data_type,
                schema=schema,
                size_bytes=size_bytes,
                record_count=record_count,
                content_type=content_type,
                lineage=lineage,
                transformation_history=process_step_objects,
                tags=tags or []
            )

            # Record initial access entry
            access_entry = {
                "accessor": self.current_user or "system",
                "access_time": datetime.datetime.now().isoformat(),
                "operation": "create",
                "details": {"initial_creation": True}
            }
            provenance.access_history.append(access_entry)

            # Add parent-child relationships to data flow
            if parent_ids:
                for parent_id in parent_ids:
                    if parent_id not in provenance.data_flow:
                        provenance.data_flow[parent_id] = []
                    provenance.data_flow[parent_id].append(data_id)

                    # Update parent provenance records if they exist
                    parent_provenance = self.get_provenance(parent_id)
                    if parent_provenance:
                        if not hasattr(parent_provenance, "lineage") or not parent_provenance.lineage:
                            # Handle older provenance records without lineage
                            continue

                        if data_id not in parent_provenance.lineage.derived_datasets:
                            parent_provenance.lineage.derived_datasets.append(data_id)
                            self._write_provenance_log(parent_provenance)

            # Store in cache
            self.provenance_cache[data_id] = provenance

            # Write to provenance log
            self._write_provenance_log(provenance)

            # Log audit event
            self._log_audit_event(
                event_type="provenance_recorded",
                user=self.current_user or "system",
                action="record_provenance",
                resource_id=data_id,
                resource_type="data",
                details={
                    "source": source,
                    "parent_count": len(parent_ids),
                    "data_type": data_type,
                    "size_bytes": size_bytes,
                    "record_count": record_count
                }
            )

            self.logger.info(f"Recorded comprehensive provenance for data {data_id} from {source}")
            return provenance

    def get_provenance(self, data_id: str, record_access: bool = True) -> Optional[DataProvenance]:
        """
        Get provenance information for a piece of data.

        This method retrieves the detailed provenance record for a specific data item.
        Optionally records this access in the data's access history if record_access is True.

        Args:
            data_id: ID of the data
            record_access: Whether to record this access in the provenance history

        Returns:
            DataProvenance: The comprehensive provenance information, or None if not found
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return None

        if not self.config.track_provenance:
            return None

        with self._lock:
            # Check cache
            provenance = None
            if data_id in self.provenance_cache:
                provenance = self.provenance_cache[data_id]
            else:
                # Look in provenance log
                provenance = self._read_provenance_log(data_id)
                if provenance:
                    # Cache for future use
                    self.provenance_cache[data_id] = provenance

            if not provenance:
                self.logger.warning(f"Provenance not found for data {data_id}")
                return None

            # Record this access if requested
            if record_access:
                access_entry = {
                    "accessor": self.current_user or "system",
                    "access_time": datetime.datetime.now().isoformat(),
                    "operation": "read",
                    "details": {"read_provenance": True}
                }

                # Handle older provenance records that might not have access_history
                if not hasattr(provenance, "access_history"):
                    provenance.access_history = []

                provenance.access_history.append(access_entry)
                self._write_provenance_log(provenance)

                # Log audit event for data access
                self._log_audit_event(
                    event_type="data_access",
                    user=self.current_user or "system",
                    action="get_provenance",
                    resource_id=data_id,
                    resource_type="data",
                    details={"operation": "read"}
                )

            return provenance

    def record_data_access(self, data_id: str, operation: str, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Record an access to a data item in its provenance information.

        This method explicitly tracks who accessed a piece of data, when, and how,
        building a comprehensive access history that can be used for audit and
        compliance purposes.

        Args:
            data_id: ID of the data being accessed
            operation: Type of access operation (e.g., "read", "update", "delete", "export")
            details: Additional details about the access

        Returns:
            bool: Whether the access was successfully recorded
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not self.config.track_provenance:
            return False

        with self._lock:
            # Get existing provenance
            provenance = self.get_provenance(data_id, record_access=False)
            if not provenance:
                self.logger.warning(f"Cannot record access: Provenance not found for data {data_id}")
                return False

            # Create access entry
            access_entry = {
                "accessor": self.current_user or "system",
                "access_time": datetime.datetime.now().isoformat(),
                "operation": operation,
                "details": details or {}
            }

            # Add to access history
            if not hasattr(provenance, "access_history"):
                provenance.access_history = []

            provenance.access_history.append(access_entry)

            # Update provenance record
            self.provenance_cache[data_id] = provenance
            self._write_provenance_log(provenance)

            # Log audit event for data access
            self._log_audit_event(
                event_type="data_access",
                user=self.current_user or "system",
                action=operation,
                resource_id=data_id,
                resource_type="data",
                details=details or {}
            )

            self.logger.debug(f"Recorded {operation} access to data {data_id} by {self.current_user or 'system'}")
            return True

    def _write_provenance_log(self, provenance: DataProvenance) -> bool:
        """
        Write provenance information to the provenance log.

        Args:
            provenance: Provenance information to write

        Returns:
            bool: Whether the write was successful
        """
        provenance_dir = os.path.join(self.config.security_dir, "provenance")
        if not os.path.exists(provenance_dir):
            os.makedirs(provenance_dir, exist_ok=True)

        # Write to individual file
        file_path = os.path.join(provenance_dir, f"{provenance.data_id}.json")
        try:
            with open(file_path, 'w') as f:
                json.dump(asdict(provenance), f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Error writing provenance log: {str(e)}")
            return False

    def _read_provenance_log(self, data_id: str) -> Optional[DataProvenance]:
        """
        Read provenance information from the provenance log.

        This method reads and reconstructs a DataProvenance object from its
        serialized form in the provenance log, handling both legacy and new
        enhanced formats.

        Args:
            data_id: ID of the data

        Returns:
            DataProvenance: The provenance information, or None if not found
        """
        provenance_dir = os.path.join(self.config.security_dir, "provenance")
        file_path = os.path.join(provenance_dir, f"{data_id}.json")

        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

                # Create basic provenance record with required fields
                provenance = DataProvenance(
                    data_id=data["data_id"],
                    source=data["source"],
                    creator=data["creator"],
                    creation_time=data["creation_time"],
                    process_steps=data["process_steps"],
                    parent_ids=data["parent_ids"],
                    version=data["version"],
                    checksum=data["checksum"],
                    metadata=data.get("metadata", {})
                )

                # Add enhanced fields if they exist in the data (for backward compatibility)
                if "data_type" in data:
                    provenance.data_type = data["data_type"]

                if "schema" in data:
                    provenance.schema = data["schema"]

                if "size_bytes" in data:
                    provenance.size_bytes = data["size_bytes"]

                if "record_count" in data:
                    provenance.record_count = data["record_count"]

                if "content_type" in data:
                    provenance.content_type = data["content_type"]

                if "retention_policy" in data:
                    provenance.retention_policy = data["retention_policy"]

                if "access_history" in data:
                    provenance.access_history = data["access_history"]

                if "data_flow" in data:
                    provenance.data_flow = data["data_flow"]

                if "tags" in data:
                    provenance.tags = data["tags"]

                if "external_references" in data:
                    provenance.external_references = data["external_references"]

                if "compliance" in data:
                    provenance.compliance = data["compliance"]

                if "verification_status" in data:
                    provenance.verification_status = data["verification_status"]

                # Process lineage if it exists
                if "lineage" in data:
                    lineage_data = data["lineage"]
                    if lineage_data:
                        provenance.lineage = DataLineage(
                            source_system=lineage_data.get("source_system", "unknown"),
                            source_type=lineage_data.get("source_type", "unknown"),
                            extraction_method=lineage_data.get("extraction_method", "unknown"),
                            extraction_time=lineage_data.get("extraction_time", ""),
                            transformations=lineage_data.get("transformations", []),
                            derived_datasets=lineage_data.get("derived_datasets", []),
                            upstream_datasets=lineage_data.get("upstream_datasets", []),
                            lineage_graph=lineage_data.get("lineage_graph", {}),
                            versioning=lineage_data.get("versioning", {}),
                            quality_metrics=lineage_data.get("quality_metrics", {})
                        )

                # Process transformation history if it exists
                if "transformation_history" in data:
                    transformation_data = data["transformation_history"]
                    if transformation_data:
                        for step_data in transformation_data:
                            step = ProcessStep(
                                step_id=step_data.get("step_id", ""),
                                operation=step_data.get("operation", "unknown"),
                                description=step_data.get("description", ""),
                                tool=step_data.get("tool", "unknown"),
                                parameters=step_data.get("parameters", {}),
                                start_time=step_data.get("start_time", ""),
                                end_time=step_data.get("end_time"),
                                status=step_data.get("status", "completed"),
                                error=step_data.get("error"),
                                inputs=step_data.get("inputs", []),
                                outputs=step_data.get("outputs", []),
                                metrics=step_data.get("metrics", {}),
                                environment=step_data.get("environment", {}),
                                operator=step_data.get("operator", "")
                            )
                            provenance.transformation_history.append(step)

                return provenance

        except Exception as e:
            self.logger.error(f"Error reading provenance log: {str(e)}")
            return None

    def search_provenance(self, criteria: Dict[str, Any],
                          limit: int = 100) -> List[DataProvenance]:
        """
        Search for data provenance records matching specified criteria.

        This method allows querying the provenance store for records matching
        specific criteria, enabling data lineage tracking, impact analysis,
        and audit searches.

        Args:
            criteria: Dictionary of search criteria
                Supported criteria include:
                - creator: Search for data created by specific user
                - source: Search for data from a specific source
                - data_type: Search by data type
                - created_after/created_before: Filter by creation time
                - tags: List of tags to match
                - parent_id: Find data derived from a specific parent
                - content_type: Filter by content type
                - tool_used: Find data processed using a specific tool
                - accessed_by: Find data accessed by a specific user
                - verification_status: Filter by verification status
            limit: Maximum number of matching records to return

        Returns:
            List[DataProvenance]: List of matching provenance records
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return []

        if not self.config.track_provenance:
            return []

        results = []
        count = 0

        # Get all provenance records
        provenance_dir = os.path.join(self.config.security_dir, "provenance")
        if not os.path.exists(provenance_dir):
            return []

        # List all provenance files
        try:
            files = [f for f in os.listdir(provenance_dir) if f.endswith('.json')]

            # Process each file
            for file in files:
                if count >= limit:
                    break

                try:
                    # Read the provenance record
                    file_path = os.path.join(provenance_dir, file)
                    with open(file_path, 'r') as f:
                        data = json.load(f)

                    # Check if it matches the criteria
                    matches = True

                    # Basic criteria
                    if 'creator' in criteria and data.get('creator') != criteria['creator']:
                        matches = False

                    if 'source' in criteria and data.get('source') != criteria['source']:
                        matches = False

                    if 'data_type' in criteria and data.get('data_type') != criteria['data_type']:
                        matches = False

                    if 'verification_status' in criteria and data.get('verification_status') != criteria['verification_status']:
                        matches = False

                    # Time-based criteria
                    if 'created_after' in criteria:
                        creation_time = datetime.datetime.fromisoformat(data.get('creation_time', '1970-01-01T00:00:00'))
                        if creation_time < datetime.datetime.fromisoformat(criteria['created_after']):
                            matches = False

                    if 'created_before' in criteria:
                        creation_time = datetime.datetime.fromisoformat(data.get('creation_time', '9999-12-31T23:59:59'))
                        if creation_time > datetime.datetime.fromisoformat(criteria['created_before']):
                            matches = False

                    # Tag criteria
                    if 'tags' in criteria and 'tags' in data:
                        for tag in criteria['tags']:
                            if tag not in data['tags']:
                                matches = False
                                break

                    # Parent criteria
                    if 'parent_id' in criteria:
                        if 'parent_ids' not in data or criteria['parent_id'] not in data['parent_ids']:
                            matches = False

                    # Content type criteria
                    if 'content_type' in criteria and data.get('content_type') != criteria['content_type']:
                        matches = False

                    # Tool criteria - more complex as it requires checking transformation history
                    if 'tool_used' in criteria and 'transformation_history' in data:
                        tool_found = False
                        for step in data['transformation_history']:
                            if step.get('tool') == criteria['tool_used']:
                                tool_found = True
                                break
                        if not tool_found:
                            matches = False

                    # Access criteria - check who accessed the data
                    if 'accessed_by' in criteria and 'access_history' in data:
                        access_found = False
                        for access in data['access_history']:
                            if access.get('accessor') == criteria['accessed_by']:
                                access_found = True
                                break
                        if not access_found:
                            matches = False

                    # If all criteria matched, reconstruct the provenance object and add to results
                    if matches:
                        provenance = self._read_provenance_log(data['data_id'])
                        if provenance:
                            results.append(provenance)
                            count += 1

                except Exception as e:
                    self.logger.error(f"Error processing provenance file {file}: {str(e)}")
                    continue

            # Log audit event for provenance search
            self._log_audit_event(
                event_type="provenance_search",
                user=self.current_user or "system",
                action="search_provenance",
                details={"criteria": criteria, "results_count": len(results)}
            )

            return results

        except Exception as e:
            self.logger.error(f"Error searching provenance: {str(e)}")
            return []

    def get_data_lineage_graph(self, data_id: str, max_depth: int = 3,
                              direction: str = "both") -> Dict[str, Any]:
        """
        Generate a lineage graph for a specific data item.

        This method builds a directed graph showing the lineage relationships
        between data items, either upstream (parents/sources), downstream
        (derived data), or both.

        Args:
            data_id: ID of the data to start from
            max_depth: Maximum depth of relationships to traverse
            direction: Direction to traverse: "upstream", "downstream", or "both"

        Returns:
            Dict[str, Any]: Graph representation of the data lineage
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return {}

        if not self.config.track_provenance:
            return {}

        # Initialize graph structure
        graph = {
            "nodes": [],
            "edges": [],
            "root_id": data_id
        }

        # Set of processed nodes to avoid cycles
        processed_nodes = set()

        # Process function to recursively build the graph
        def process_node(node_id, current_depth=0, node_type="target"):
            # Skip if we've reached max depth or already processed this node
            if current_depth > max_depth or node_id in processed_nodes:
                return

            # Mark node as processed
            processed_nodes.add(node_id)

            # Get node data
            provenance = self.get_provenance(node_id, record_access=False)
            if not provenance:
                return

            # Add node to graph
            node_data = {
                "id": node_id,
                "type": node_type,
                "data_type": getattr(provenance, "data_type", "unknown"),
                "source": provenance.source,
                "creator": provenance.creator,
                "creation_time": provenance.creation_time,
                "version": provenance.version
            }

            # Add tags if available
            if hasattr(provenance, "tags") and provenance.tags:
                node_data["tags"] = provenance.tags

            graph["nodes"].append(node_data)

            # Process upstream (parents) if direction allows
            if direction in ["upstream", "both"]:
                for parent_id in provenance.parent_ids:
                    # Add edge from parent to node
                    edge = {
                        "source": parent_id,
                        "target": node_id,
                        "type": "parent"
                    }
                    graph["edges"].append(edge)

                    # Recurse to process parent
                    process_node(parent_id, current_depth + 1, "parent")

            # Process downstream (derived) if direction allows
            if direction in ["downstream", "both"] and hasattr(provenance, "lineage") and provenance.lineage:
                for derived_id in provenance.lineage.derived_datasets:
                    # Add edge from node to derived
                    edge = {
                        "source": node_id,
                        "target": derived_id,
                        "type": "derived"
                    }
                    graph["edges"].append(edge)

                    # Recurse to process derived
                    process_node(derived_id, current_depth + 1, "derived")

        # Start building graph from the target node
        process_node(data_id)

        # Log audit event for lineage graph generation
        self._log_audit_event(
            event_type="lineage_graph_generated",
            user=self.current_user or "system",
            action="get_data_lineage_graph",
            resource_id=data_id,
            resource_type="data",
            details={
                "max_depth": max_depth,
                "direction": direction,
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"])
            }
        )

        return graph

    def _log_audit_event(self, event_type: str, user: str, action: str,
                        resource_id: Optional[str] = None, resource_type: Optional[str] = None,
                        details: Optional[Dict[str, Any]] = None, source_ip: Optional[str] = None,
                        success: bool = True) -> None:
        """
        Log an audit event.

        Args:
            event_type: Type of event
            user: User who triggered the event
            action: Action performed
            resource_id: ID of the resource involved
            resource_type: Type of the resource involved
            details: Additional details about the event
            source_ip: Source IP address
            success: Whether the action was successful
        """
        if not self.config.log_all_access:
            return

        # Create event
        event = AuditLogEntry(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.datetime.now().isoformat(),
            event_type=event_type,
            user=user,
            resource_id=resource_id,
            resource_type=resource_type,
            action=action,
            status="success" if success else "failure",
            details=details or {},
            source_ip=source_ip,
            success=success
        )

        # Write to audit log
        self._write_audit_log(event)

        # Log using monitoring system if available
        if MONITORING_AVAILABLE:
            metrics = get_metrics_registry()
            metrics.event(
                name="security_audit_event",
                data=asdict(event),
                labels={"event_type": event_type, "user": user, "success": str(success)}
            )

    def record_transformation_step(self, data_id: str, operation: str, description: str,
                                  tool: str, parameters: Dict[str, Any],
                                  inputs: List[str], outputs: Optional[List[str]] = None,
                                  metrics: Optional[Dict[str, Any]] = None,
                                  environment: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        Record a data transformation step in the provenance information.

        This method adds a detailed record of a processing step to a data item's
        transformation history, enabling comprehensive tracking of all operations
        performed on the data throughout its lifecycle.

        Args:
            data_id: ID of the data being transformed
            operation: Type of operation (e.g., "filter", "transform", "join")
            description: Human-readable description of the operation
            tool: Tool/library used for the operation
            parameters: Parameters used for the operation
            inputs: Input data identifiers for this operation
            outputs: Output data identifiers from this operation
            metrics: Performance metrics for the operation
            environment: Execution environment details

        Returns:
            str: ID of the recorded step, or None if recording failed
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return None

        if not self.config.track_provenance:
            return None

        with self._lock:
            # Get existing provenance
            provenance = self.get_provenance(data_id, record_access=False)
            if not provenance:
                self.logger.warning(f"Cannot record transformation: Provenance not found for data {data_id}")
                return None

            # Generate step ID
            step_id = str(uuid.uuid4())

            # Create step
            step = ProcessStep(
                step_id=step_id,
                operation=operation,
                description=description,
                tool=tool,
                parameters=parameters,
                start_time=datetime.datetime.now().isoformat(),
                end_time=None,  # Will be set when step is completed
                status="running",
                inputs=inputs,
                outputs=outputs or [],
                metrics=metrics or {},
                environment=environment or {},
                operator=self.current_user or "system"
            )

            # Add to transformation history
            if not hasattr(provenance, "transformation_history"):
                provenance.transformation_history = []

            provenance.transformation_history.append(step)

            # Update lineage information
            if not provenance.lineage:
                # Create lineage if it doesn't exist
                provenance.lineage = DataLineage(
                    source_system="internal",
                    source_type="transformation",
                    extraction_method="internal",
                    extraction_time=datetime.datetime.now().isoformat()
                )

            # Add step ID to lineage transformations
            provenance.lineage.transformations.append(step_id)

            # Update provenance record
            self.provenance_cache[data_id] = provenance
            self._write_provenance_log(provenance)

            # Log audit event
            self._log_audit_event(
                event_type="transformation_started",
                user=self.current_user or "system",
                action=operation,
                resource_id=data_id,
                resource_type="data",
                details={
                    "step_id": step_id,
                    "tool": tool,
                    "inputs": inputs
                }
            )

            self.logger.info(f"Started transformation step {step_id} on data {data_id}")
            return step_id

    def complete_transformation_step(self, data_id: str, step_id: str,
                                   status: str = "completed",
                                   error: Optional[str] = None,
                                   outputs: Optional[List[str]] = None,
                                   metrics: Optional[Dict[str, Any]] = None) -> bool:
        """
        Mark a transformation step as completed and update its details.

        Args:
            data_id: ID of the data being transformed
            step_id: ID of the step to update
            status: Final status of the step (completed, failed)
            error: Error message if status is failed
            outputs: Output data identifiers (to update)
            metrics: Final performance metrics

        Returns:
            bool: Whether the update was successful
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not self.config.track_provenance:
            return False

        with self._lock:
            # Get existing provenance
            provenance = self.get_provenance(data_id, record_access=False)
            if not provenance:
                self.logger.warning(f"Cannot complete transformation: Provenance not found for data {data_id}")
                return False

            # Find the step
            step_found = False
            for step in provenance.transformation_history:
                if step.step_id == step_id:
                    # Update step
                    step.end_time = datetime.datetime.now().isoformat()
                    step.status = status
                    if error:
                        step.error = error
                    if outputs:
                        step.outputs = outputs
                    if metrics:
                        step.metrics.update(metrics)
                    step_found = True
                    break

            if not step_found:
                self.logger.warning(f"Step {step_id} not found in transformation history for data {data_id}")
                return False

            # Update provenance record
            self.provenance_cache[data_id] = provenance
            self._write_provenance_log(provenance)

            # Log audit event
            self._log_audit_event(
                event_type="transformation_completed",
                user=self.current_user or "system",
                action="complete_transformation",
                resource_id=data_id,
                resource_type="data",
                details={
                    "step_id": step_id,
                    "status": status,
                    "has_error": error is not None
                }
            )

            self.logger.info(f"Completed transformation step {step_id} on data {data_id} with status {status}")
            return True

    def verify_data_provenance(self, data_id: str, verification_method: str = "checksum",
                            verification_details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Verify the integrity and provenance of a data item.

        This method validates the data's integrity through various verification
        methods such as checksum validation, parent consistency checking, or
        external validation services.

        Args:
            data_id: ID of the data to verify
            verification_method: Method used for verification (checksum, parent_consistency, external)
            verification_details: Additional details required for verification

        Returns:
            bool: Whether the verification was successful
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not self.config.track_provenance:
            return False

        with self._lock:
            # Get existing provenance
            provenance = self.get_provenance(data_id, record_access=False)
            if not provenance:
                self.logger.warning(f"Cannot verify provenance: Provenance not found for data {data_id}")
                return False

            verification_success = False
            verification_result = {
                "method": verification_method,
                "timestamp": datetime.datetime.now().isoformat(),
                "verifier": self.current_user or "system",
                "details": verification_details or {}
            }

            # Perform verification based on method
            if verification_method == "checksum":
                # Checksum verification requires the actual data checksum to be provided
                if not verification_details or "actual_checksum" not in verification_details:
                    self.logger.error("Checksum verification requires 'actual_checksum' in verification_details")
                    verification_result["success"] = False
                    verification_result["error"] = "Missing actual_checksum in verification details"
                else:
                    actual_checksum = verification_details["actual_checksum"]
                    expected_checksum = provenance.checksum

                    verification_success = actual_checksum == expected_checksum
                    verification_result["success"] = verification_success
                    if not verification_success:
                        verification_result["error"] = "Checksum mismatch"
                        verification_result["expected"] = expected_checksum
                        verification_result["actual"] = actual_checksum

            elif verification_method == "parent_consistency":
                # Verify that parent records exist and are consistent
                all_parents_valid = True
                invalid_parents = []

                for parent_id in provenance.parent_ids:
                    parent = self.get_provenance(parent_id, record_access=False)
                    if not parent:
                        all_parents_valid = False
                        invalid_parents.append({"parent_id": parent_id, "error": "Parent not found"})

                verification_success = all_parents_valid
                verification_result["success"] = verification_success
                if not verification_success:
                    verification_result["error"] = "Parent consistency check failed"
                    verification_result["invalid_parents"] = invalid_parents

            elif verification_method == "external":
                # External verification service
                if not verification_details or "service_response" not in verification_details:
                    self.logger.error("External verification requires 'service_response' in verification_details")
                    verification_result["success"] = False
                    verification_result["error"] = "Missing service_response in verification details"
                else:
                    service_response = verification_details["service_response"]
                    verification_success = service_response.get("verified", False)
                    verification_result["success"] = verification_success
                    verification_result["service_details"] = service_response

            else:
                self.logger.error(f"Unknown verification method: {verification_method}")
                verification_result["success"] = False
                verification_result["error"] = f"Unknown verification method: {verification_method}"

            # Update verification status
            provenance.verification_status = "verified" if verification_success else "failed"

            # Store verification result in metadata
            if "verification_history" not in provenance.metadata:
                provenance.metadata["verification_history"] = []

            provenance.metadata["verification_history"].append(verification_result)

            # Update provenance record
            self.provenance_cache[data_id] = provenance
            self._write_provenance_log(provenance)

            # Log audit event
            self._log_audit_event(
                event_type="provenance_verification",
                user=self.current_user or "system",
                action="verify_provenance",
                resource_id=data_id,
                resource_type="data",
                details={
                    "method": verification_method,
                    "success": verification_success
                },
                success=verification_success
            )

            self.logger.info(f"Verified provenance for data {data_id} using {verification_method}: {verification_success}")
            return verification_success

    def _write_audit_log(self, event: AuditLogEntry) -> bool:
        """
        Write an audit event to the audit log.

        Args:
            event: Audit event to write

        Returns:
            bool: Whether the write was successful
        """
        audit_log_path = self.config.audit_log_path
        if not audit_log_path:
            audit_log_path = os.path.join(self.config.security_dir, "audit.log")

        try:
            # Create directory if needed
            audit_log_dir = os.path.dirname(audit_log_path)
            if not os.path.exists(audit_log_dir):
                os.makedirs(audit_log_dir, exist_ok=True)

            # Write event as JSON
            with open(audit_log_path, 'a') as f:
                f.write(json.dumps(asdict(event)) + "\n")

            return True
        except Exception as e:
            self.logger.error(f"Error writing audit log: {str(e)}")
            return False

    def get_audit_logs(self, filters: Optional[Dict[str, Any]] = None,
                     limit: int = 100, offset: int = 0) -> List[AuditLogEntry]:
        """
        Get audit logs, optionally filtered.

        Args:
            filters: Filters to apply
            limit: Maximum number of logs to return
            offset: Offset for pagination

        Returns:
            list: List of audit log entries
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return []

        audit_log_path = self.config.audit_log_path
        if not audit_log_path:
            audit_log_path = os.path.join(self.config.security_dir, "audit.log")

        if not os.path.exists(audit_log_path):
            return []

        try:
            logs = []
            with open(audit_log_path, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())

                        # Apply filters
                        if filters:
                            match = True
                            for key, value in filters.items():
                                if key in data and data[key] != value:
                                    match = False
                                    break

                            if not match:
                                continue

                        # Create entry
                        entry = AuditLogEntry(
                            event_id=data["event_id"],
                            timestamp=data["timestamp"],
                            event_type=data["event_type"],
                            user=data["user"],
                            resource_id=data["resource_id"],
                            resource_type=data["resource_type"],
                            action=data["action"],
                            status=data["status"],
                            details=data["details"],
                            source_ip=data.get("source_ip"),
                            success=data["success"]
                        )

                        logs.append(entry)

                        # Apply limit
                        if len(logs) >= offset + limit:
                            break
                    except Exception as e:
                        self.logger.error(f"Error parsing audit log entry: {str(e)}")

            # Apply offset
            return logs[offset:offset+limit]

        except Exception as e:
            self.logger.error(f"Error reading audit logs: {str(e)}")
            return []

    # UCAN-specific methods for capability-based authorization

    def delegate_encryption_capability(self, key_id: str, delegator_did: str, delegatee_did: str,
                                      action: str, caveats: Optional[Dict[str, Any]] = None,
                                      ttl: Optional[int] = None) -> Optional[str]:
        """
        Delegate a capability for an encryption key to another DID.

        This method enables secure delegation of capabilities from one principal to another.
        It implements the core UCAN delegation pattern, creating a chain of authorization
        between the original key DID and downstream recipients.

        The delegation process:
        1. Verifies delegator has both the capability being delegated and delegation rights
        2. Creates a new UCAN token with capabilities that are equal or more restricted than
           the delegator's capabilities
        3. Establishes a cryptographic chain through token signatures and proofs
        4. Provides optional caveats to restrict the delegated capability (time limits,
           usage counts, etc.)

        Args:
            key_id: ID of the encryption key
            delegator_did: DID of the delegator
            delegatee_did: DID of the delegatee
            action: Capability action to delegate (encrypt, decrypt, delegate, etc.)
            caveats: Caveats on the capability (restrictions like expiry, max uses, etc.)
            ttl: Time-to-live in seconds (default uses the configuration value)

        Returns:
            str: ID of the created token, or None if delegation failed

        Example:
            ```python
            # Delegate encryption capability from Alice to Bob
            token_id = security.delegate_encryption_capability(
                key_id="a1b2c3...",
                delegator_did="did:key:alice...",
                delegatee_did="did:key:bob...",
                action="encrypt",
                caveats={"max_uses": 5},
                ttl=3600  # 1 hour
            )
            ```
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return None

        if not self.config.use_ucan or not UCAN_AVAILABLE or not self.ucan_manager:
            self.logger.error("UCAN is not available or not enabled")
            return None

        if key_id not in self.encryption_keys:
            self.logger.error(f"Encryption key {key_id} not found")
            return None

        key = self.encryption_keys[key_id]

        # Check if delegator has the capability
        if not self._check_key_capability(delegator_did, key_id, action):
            self.logger.error(f"Delegator {delegator_did} does not have {action} capability for key {key_id}")
            return None

        # Check if delegator has delegation capability
        if not self._check_key_capability(delegator_did, key_id, "delegate"):
            self.logger.error(f"Delegator {delegator_did} does not have delegate capability for key {key_id}")
            return None

        # Create delegation
        token = self.ucan_manager.delegate_capability(
            issuer_did=delegator_did,
            audience_did=delegatee_did,
            resource=key_id,
            action=action,
            caveats=caveats,
            ttl=ttl or self.config.default_capability_ttl
        )

        if token:
            # Log audit event
            self._log_audit_event(
                event_type="capability_delegated",
                user=self.current_user or "system",
                action="delegate_capability",
                resource_id=key_id,
                resource_type="encryption_key",
                details={
                    "delegator_did": delegator_did,
                    "delegatee_did": delegatee_did,
                    "action": action,
                    "token_id": token.token_id
                }
            )

            self.logger.info(f"Delegated {action} capability for key {key_id} from {delegator_did} to {delegatee_did}")
            return token.token_id

        return None

    def revoke_encryption_capability(self, token_id: str, revoker_did: str, reason: str) -> bool:
        """
        Revoke a capability delegation for an encryption key.

        This method revokes a previously delegated UCAN token, invalidating the capabilities
        it grants. Revocation is an important security mechanism that allows principals to
        stop delegated capabilities from being used, even before they expire.

        The revocation process:
        1. Verifies the revoker is either the issuer or audience of the token
        2. Creates a revocation record that will be checked during capability validation
        3. Logs the revocation event with the provided reason

        Only the original issuer of a token or its recipient (audience) can revoke it.
        Revocations are permanent and cannot be undone.

        Args:
            token_id: ID of the token to revoke
            revoker_did: DID of the revoker (must be issuer or audience)
            reason: Reason for revocation (for audit purposes)

        Returns:
            bool: Whether revocation was successful

        Example:
            ```python
            # Revoke Bob's encryption capability
            revoked = security.revoke_encryption_capability(
                token_id="t1b2c3...",
                revoker_did="did:key:alice...",  # Alice is revoking the capability she granted
                reason="Security policy change"
            )
            ```
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return False

        if not self.config.use_ucan or not UCAN_AVAILABLE or not self.ucan_manager:
            self.logger.error("UCAN is not available or not enabled")
            return False

        # Get token
        token = self.ucan_manager.get_token(token_id)
        if not token:
            self.logger.error(f"Token {token_id} not found")
            return False

        # Check if revoker is issuer or audience
        if revoker_did != token.issuer and revoker_did != token.audience:
            self.logger.error(f"Revoker {revoker_did} is neither issuer nor audience of token {token_id}")
            return False

        # Revoke token
        revoked = self.ucan_manager.revoke_token(token_id, revoker_did, reason)

        if revoked:
            # Get key ID from token capabilities
            key_id = None
            for cap in token.capabilities:
                key_id = cap.resource
                break

            # Log audit event
            self._log_audit_event(
                event_type="capability_revoked",
                user=self.current_user or "system",
                action="revoke_capability",
                resource_id=key_id,
                resource_type="encryption_key",
                details={
                    "revoker_did": revoker_did,
                    "token_id": token_id,
                    "reason": reason
                }
            )

            self.logger.info(f"Revoked token {token_id} by {revoker_did} for reason: {reason}")

        return revoked

    def generate_provenance_report(self, data_id: str, report_type: str = "detailed",
                                 format: str = "json", include_lineage: bool = True,
                                 include_access_history: bool = True) -> Dict[str, Any]:
        """
        Generate a comprehensive report of a data item's provenance information.

        This method produces a formatted report of a data item's provenance,
        including its lineage, transformation history, access patterns, and
        verification status. The report can be generated in different formats
        and levels of detail.

        Args:
            data_id: ID of the data to report on
            report_type: Type of report to generate (summary, detailed, technical, compliance)
            format: Format of the report (json, text, html, markdown)
            include_lineage: Whether to include detailed lineage information
            include_access_history: Whether to include access history

        Returns:
            Dict[str, Any]: The generated report data
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return {"error": "Security manager not initialized"}

        # Get provenance data
        provenance = self.get_provenance(data_id, record_access=True)
        if not provenance:
            self.logger.error(f"Provenance information for {data_id} not found")
            return {"error": f"Provenance information for {data_id} not found"}

        # Initialize report structure
        report = {
            "report_type": report_type,
            "generated_at": datetime.datetime.now().isoformat(),
            "data_id": data_id,
            "report_format": format,
            "data_info": {
                "data_id": provenance.data_id,
                "data_type": provenance.data_type,
                "source": provenance.source,
                "creator": provenance.creator,
                "creation_time": provenance.creation_time,
                "version": provenance.version,
                "size_bytes": provenance.size_bytes,
                "record_count": provenance.record_count,
                "content_type": provenance.content_type,
                "verification_status": provenance.verification_status,
                "tags": provenance.tags if hasattr(provenance, "tags") else [],
            },
            "verification": {
                "verification_status": provenance.verification_status,
                "checksum": provenance.checksum,
                "last_verified": self._get_last_verification_time(provenance),
            }
        }

        # Add detailed information based on report type
        if report_type in ["detailed", "technical"]:
            report["metadata"] = provenance.metadata
            report["schema"] = provenance.schema

            # Include parent/child relationships
            report["relationships"] = {
                "parent_ids": provenance.parent_ids,
                "derived_data": self._get_derived_data_ids(data_id)
            }

            # Include compliance info if available
            if hasattr(provenance, "compliance") and provenance.compliance:
                report["compliance"] = provenance.compliance

            # Include external references if available
            if hasattr(provenance, "external_references") and provenance.external_references:
                report["external_references"] = provenance.external_references

        # Include transformation history for detailed and technical reports
        if report_type in ["detailed", "technical"]:
            if hasattr(provenance, "transformation_history") and provenance.transformation_history:
                transformations = []
                for step in provenance.transformation_history:
                    step_info = {
                        "step_id": step.step_id,
                        "operation": step.operation,
                        "description": step.description,
                        "tool": step.tool,
                        "start_time": step.start_time,
                        "end_time": step.end_time,
                        "status": step.status,
                    }

                    # Add more technical details for technical reports
                    if report_type == "technical":
                        step_info["parameters"] = step.parameters
                        step_info["inputs"] = step.inputs
                        step_info["outputs"] = step.outputs
                        step_info["metrics"] = step.metrics
                        step_info["environment"] = step.environment
                        step_info["operator"] = step.operator
                        if step.error:
                            step_info["error"] = step.error

                    transformations.append(step_info)

                report["transformation_history"] = transformations

        # Include lineage information if requested
        if include_lineage and hasattr(provenance, "lineage") and provenance.lineage:
            lineage_info = {
                "source_system": provenance.lineage.source_system,
                "source_type": provenance.lineage.source_type,
                "extraction_method": provenance.lineage.extraction_method,
                "extraction_time": provenance.lineage.extraction_time,
            }

            if report_type in ["detailed", "technical"]:
                lineage_info["upstream_datasets"] = provenance.lineage.upstream_datasets
                lineage_info["derived_datasets"] = provenance.lineage.derived_datasets

                if report_type == "technical":
                    lineage_info["transformations"] = provenance.lineage.transformations
                    lineage_info["lineage_graph"] = provenance.lineage.lineage_graph
                    lineage_info["versioning"] = provenance.lineage.versioning
                    lineage_info["quality_metrics"] = provenance.lineage.quality_metrics

            report["lineage"] = lineage_info

        # Include access history if requested
        if include_access_history and hasattr(provenance, "access_history") and provenance.access_history:
            if report_type in ["summary", "compliance"]:
                # For summary, just include count and last access
                report["access_summary"] = {
                    "total_accesses": len(provenance.access_history),
                    "last_access": provenance.access_history[-1]["timestamp"] if provenance.access_history else None,
                    "unique_accessors": len(set(entry["user"] for entry in provenance.access_history))
                }
            else:
                # For detailed/technical, include full history
                if report_type == "technical":
                    report["access_history"] = provenance.access_history
                else:
                    # For detailed, include simplified access entries
                    simplified_history = []
                    for entry in provenance.access_history:
                        simplified_history.append({
                            "user": entry["user"],
                            "timestamp": entry["timestamp"],
                            "operation": entry["operation"]
                        })
                    report["access_history"] = simplified_history

        # Format the report if needed
        if format == "text":
            return self._format_report_as_text(report)
        elif format == "html":
            return self._format_report_as_html(report)
        elif format == "markdown":
            return self._format_report_as_markdown(report)

        # Default: return as JSON-serializable dict
        return report

    def _get_last_verification_time(self, provenance: DataProvenance) -> Optional[str]:
        """Helper to get the last verification time from a provenance record."""
        if hasattr(provenance, "access_history") and provenance.access_history:
            # Look for verification operations in access history
            verifications = [
                entry["timestamp"] for entry in provenance.access_history
                if entry.get("operation") == "verify"
            ]
            if verifications:
                return max(verifications)  # Return the most recent
        return None

    def _get_derived_data_ids(self, data_id: str) -> List[str]:
        """Helper to find all data items derived from the given data ID."""
        derived_ids = []

        # Search all provenance records for those with this data_id as a parent
        for prov_id, provenance in self.provenance_cache.items():
            if data_id in provenance.parent_ids:
                derived_ids.append(prov_id)

        # If we need to search on disk as well, we would need to scan the provenance directory
        # This is a simplified implementation that only checks the cache

        return derived_ids

    def _format_report_as_text(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Format the provenance report as human-readable text."""
        text_report = report.copy()
        text_content = []

        # Add report header
        text_content.append(f"PROVENANCE REPORT: {report['data_id']}")
        text_content.append(f"Generated: {report['generated_at']}")
        text_content.append(f"Report Type: {report['report_type']}")
        text_content.append("-" * 80)

        # Add data information
        text_content.append("DATA INFORMATION:")
        for key, value in report["data_info"].items():
            if value is not None:
                text_content.append(f"  {key}: {value}")

        # Add verification information
        text_content.append("\nVERIFICATION:")
        for key, value in report["verification"].items():
            if value is not None:
                text_content.append(f"  {key}: {value}")

        # Add lineage information if available
        if "lineage" in report:
            text_content.append("\nLINEAGE INFORMATION:")
            for key, value in report["lineage"].items():
                if value is not None and not isinstance(value, (dict, list)):
                    text_content.append(f"  {key}: {value}")

            # Add upstream/downstream datasets if available
            if "upstream_datasets" in report["lineage"] and report["lineage"]["upstream_datasets"]:
                text_content.append("\n  Upstream Datasets:")
                for ds in report["lineage"]["upstream_datasets"]:
                    text_content.append(f"    - {ds}")

            if "derived_datasets" in report["lineage"] and report["lineage"]["derived_datasets"]:
                text_content.append("\n  Derived Datasets:")
                for ds in report["lineage"]["derived_datasets"]:
                    text_content.append(f"    - {ds}")

        # Add transformation history if available
        if "transformation_history" in report and report["transformation_history"]:
            text_content.append("\nTRANSFORMATION HISTORY:")
            for i, step in enumerate(report["transformation_history"]):
                text_content.append(f"\n  Step {i+1}: {step['operation']}")
                text_content.append(f"    Description: {step['description']}")
                text_content.append(f"    Tool: {step['tool']}")
                text_content.append(f"    Started: {step['start_time']}")
                text_content.append(f"    Status: {step['status']}")
                if "end_time" in step and step["end_time"]:
                    text_content.append(f"    Completed: {step['end_time']}")

        # Add access history if available
        if "access_history" in report and report["access_history"]:
            text_content.append("\nACCESS HISTORY:")
            for entry in report["access_history"]:
                text_content.append(f"  {entry['timestamp']} - {entry['user']} - {entry['operation']}")
        elif "access_summary" in report:
            text_content.append("\nACCESS SUMMARY:")
            for key, value in report["access_summary"].items():
                text_content.append(f"  {key}: {value}")

        # Join all text content
        text_report["text_content"] = "\n".join(text_content)
        return text_report

    def _format_report_as_html(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Format the provenance report as HTML."""
        html_report = report.copy()
        html_content = []

        # Basic HTML structure
        html_content.append("<!DOCTYPE html>")
        html_content.append("<html>")
        html_content.append("<head>")
        html_content.append(f"<title>Provenance Report: {report['data_id']}</title>")
        html_content.append("<style>")
        html_content.append("body { font-family: Arial, sans-serif; margin: 20px; }")
        html_content.append("h1, h2, h3 { color: #2c3e50; }")
        html_content.append("table { border-collapse: collapse; width: 100%; }")
        html_content.append("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
        html_content.append("th { background-color: #f2f2f2; }")
        html_content.append("tr:nth-child(even) { background-color: #f9f9f9; }")
        html_content.append("</style>")
        html_content.append("</head>")
        html_content.append("<body>")

        # Report header
        html_content.append(f"<h1>Provenance Report: {report['data_id']}</h1>")
        html_content.append(f"<p><strong>Generated:</strong> {report['generated_at']}</p>")
        html_content.append(f"<p><strong>Report Type:</strong> {report['report_type']}</p>")

        # Data information section
        html_content.append("<h2>Data Information</h2>")
        html_content.append("<table>")
        html_content.append("<tr><th>Property</th><th>Value</th></tr>")
        for key, value in report["data_info"].items():
            if value is not None:
                html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        html_content.append("</table>")

        # Verification section
        html_content.append("<h2>Verification</h2>")
        html_content.append("<table>")
        html_content.append("<tr><th>Property</th><th>Value</th></tr>")
        for key, value in report["verification"].items():
            if value is not None:
                html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        html_content.append("</table>")

        # Lineage section
        if "lineage" in report:
            html_content.append("<h2>Lineage Information</h2>")
            html_content.append("<table>")
            html_content.append("<tr><th>Property</th><th>Value</th></tr>")
            for key, value in report["lineage"].items():
                if value is not None and not isinstance(value, (dict, list)):
                    html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
            html_content.append("</table>")

            # Upstream/downstream datasets
            if "upstream_datasets" in report["lineage"] and report["lineage"]["upstream_datasets"]:
                html_content.append("<h3>Upstream Datasets</h3>")
                html_content.append("<ul>")
                for ds in report["lineage"]["upstream_datasets"]:
                    html_content.append(f"<li>{ds}</li>")
                html_content.append("</ul>")

            if "derived_datasets" in report["lineage"] and report["lineage"]["derived_datasets"]:
                html_content.append("<h3>Derived Datasets</h3>")
                html_content.append("<ul>")
                for ds in report["lineage"]["derived_datasets"]:
                    html_content.append(f"<li>{ds}</li>")
                html_content.append("</ul>")

        # Transformation history
        if "transformation_history" in report and report["transformation_history"]:
            html_content.append("<h2>Transformation History</h2>")
            html_content.append("<table>")
            html_content.append("<tr><th>Step</th><th>Operation</th><th>Description</th><th>Tool</th><th>Started</th><th>Status</th><th>Completed</th></tr>")
            for i, step in enumerate(report["transformation_history"]):
                end_time = step.get("end_time", "")
                html_content.append(f"<tr>")
                html_content.append(f"<td>{i+1}</td>")
                html_content.append(f"<td>{step['operation']}</td>")
                html_content.append(f"<td>{step['description']}</td>")
                html_content.append(f"<td>{step['tool']}</td>")
                html_content.append(f"<td>{step['start_time']}</td>")
                html_content.append(f"<td>{step['status']}</td>")
                html_content.append(f"<td>{end_time}</td>")
                html_content.append(f"</tr>")
            html_content.append("</table>")

        # Access history or summary
        if "access_history" in report and report["access_history"]:
            html_content.append("<h2>Access History</h2>")
            html_content.append("<table>")
            html_content.append("<tr><th>Timestamp</th><th>User</th><th>Operation</th></tr>")
            for entry in report["access_history"]:
                html_content.append(f"<tr>")
                html_content.append(f"<td>{entry['timestamp']}</td>")
                html_content.append(f"<td>{entry['user']}</td>")
                html_content.append(f"<td>{entry['operation']}</td>")
                html_content.append(f"</tr>")
            html_content.append("</table>")
        elif "access_summary" in report:
            html_content.append("<h2>Access Summary</h2>")
            html_content.append("<table>")
            html_content.append("<tr><th>Property</th><th>Value</th></tr>")
            for key, value in report["access_summary"].items():
                html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
            html_content.append("</table>")

        # Close HTML tags
        html_content.append("</body>")
        html_content.append("</html>")

        # Join all HTML content
        html_report["html_content"] = "\n".join(html_content)
        return html_report

    def _format_report_as_markdown(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Format the provenance report as Markdown."""
        md_report = report.copy()
        md_content = []

        # Report header
        md_content.append(f"# Provenance Report: {report['data_id']}")
        md_content.append(f"**Generated:** {report['generated_at']}  ")
        md_content.append(f"**Report Type:** {report['report_type']}  ")
        md_content.append("")

        # Data information section
        md_content.append("## Data Information")
        md_content.append("")
        md_content.append("| Property | Value |")
        md_content.append("| -------- | ----- |")
        for key, value in report["data_info"].items():
            if value is not None:
                md_content.append(f"| {key} | {value} |")
        md_content.append("")

        # Verification section
        md_content.append("## Verification")
        md_content.append("")
        md_content.append("| Property | Value |")
        md_content.append("| -------- | ----- |")
        for key, value in report["verification"].items():
            if value is not None:
                md_content.append(f"| {key} | {value} |")
        md_content.append("")

        # Lineage section
        if "lineage" in report:
            md_content.append("## Lineage Information")
            md_content.append("")
            md_content.append("| Property | Value |")
            md_content.append("| -------- | ----- |")
            for key, value in report["lineage"].items():
                if value is not None and not isinstance(value, (dict, list)):
                    md_content.append(f"| {key} | {value} |")
            md_content.append("")

            # Upstream/downstream datasets
            if "upstream_datasets" in report["lineage"] and report["lineage"]["upstream_datasets"]:
                md_content.append("### Upstream Datasets")
                md_content.append("")
                for ds in report["lineage"]["upstream_datasets"]:
                    md_content.append(f"- {ds}")
                md_content.append("")

            if "derived_datasets" in report["lineage"] and report["lineage"]["derived_datasets"]:
                md_content.append("### Derived Datasets")
                md_content.append("")
                for ds in report["lineage"]["derived_datasets"]:
                    md_content.append(f"- {ds}")
                md_content.append("")

        # Transformation history
        if "transformation_history" in report and report["transformation_history"]:
            md_content.append("## Transformation History")
            md_content.append("")
            md_content.append("| Step | Operation | Description | Tool | Started | Status | Completed |")
            md_content.append("| ---- | --------- | ----------- | ---- | ------- | ------ | --------- |")
            for i, step in enumerate(report["transformation_history"]):
                end_time = step.get("end_time", "")
                md_content.append(f"| {i+1} | {step['operation']} | {step['description']} | {step['tool']} | {step['start_time']} | {step['status']} | {end_time} |")
            md_content.append("")

        # Access history or summary
        if "access_history" in report and report["access_history"]:
            md_content.append("## Access History")
            md_content.append("")
            md_content.append("| Timestamp | User | Operation |")
            md_content.append("| --------- | ---- | --------- |")
            for entry in report["access_history"]:
                md_content.append(f"| {entry['timestamp']} | {entry['user']} | {entry['operation']} |")
            md_content.append("")
        elif "access_summary" in report:
            md_content.append("## Access Summary")
            md_content.append("")
            md_content.append("| Property | Value |")
            md_content.append("| -------- | ----- |")
            for key, value in report["access_summary"].items():
                md_content.append(f"| {key} | {value} |")
            md_content.append("")

        # Join all markdown content
        md_report["markdown_content"] = "\n".join(md_content)
        return md_report

    def generate_lineage_visualization(self, data_id: str, format: str = "dot",
                                     max_depth: int = 3, direction: str = "both",
                                     include_attributes: bool = False) -> Dict[str, Any]:
        """
        Generate a visualization of data lineage for a specific data item.

        This method creates a visual representation of data lineage relationships
        in various formats, suitable for rendering as graphs to help users understand
        data dependencies, transformations, and provenance relationships.

        Args:
            data_id: ID of the data to visualize lineage for
            format: Output format (dot, json, mermaid, d3)
            max_depth: Maximum depth of relationships to include
            direction: Direction to visualize (upstream, downstream, both)
            include_attributes: Whether to include node/edge attributes

        Returns:
            Dict[str, Any]: Visualization data in the requested format
        """
        if not self.initialized:
            self.logger.error("Security manager not initialized")
            return {"error": "Security manager not initialized"}

        # Get data lineage graph
        lineage_graph = self.get_data_lineage_graph(data_id, max_depth, direction)
        if "error" in lineage_graph:
            return lineage_graph

        # Get provenance information for each node
        nodes_info = {}
        for node_id in lineage_graph["nodes"]:
            prov = self.get_provenance(node_id, record_access=False)
            if prov:
                nodes_info[node_id] = {
                    "id": node_id,
                    "type": prov.data_type,
                    "creator": prov.creator,
                    "creation_time": prov.creation_time,
                    "label": self._get_node_label(prov)
                }

                if include_attributes:
                    nodes_info[node_id]["attributes"] = {
                        "size_bytes": prov.size_bytes,
                        "record_count": prov.record_count,
                        "verification_status": prov.verification_status,
                        "tags": prov.tags if hasattr(prov, "tags") else []
                    }
            else:
                # Basic info if provenance not available
                nodes_info[node_id] = {
                    "id": node_id,
                    "label": node_id,
                    "type": "unknown"
                }

        # Get edge information
        edges_info = []
        for edge in lineage_graph["edges"]:
            edge_info = {
                "source": edge["source"],
                "target": edge["target"],
                "relationship": edge["relationship"]
            }

            if include_attributes and "attributes" in edge:
                edge_info["attributes"] = edge["attributes"]

            edges_info.append(edge_info)

        # Format the visualization
        visualization = {
            "data_id": data_id,
            "max_depth": max_depth,
            "direction": direction,
            "nodes": list(nodes_info.values()),
            "edges": edges_info,
            "generated_at": datetime.datetime.now().isoformat()
        }

        # Convert to requested format
        if format == "dot":
            return self._format_lineage_as_dot(visualization)
        elif format == "mermaid":
            return self._format_lineage_as_mermaid(visualization)
        elif format == "d3":
            return self._format_lineage_as_d3(visualization)

        # Default: return as JSON-serializable dict
        return visualization

    def _get_node_label(self, provenance: DataProvenance) -> str:
        """Helper to generate a readable label for a node in the lineage graph."""
        # Use a descriptive name if available in metadata
        if provenance.metadata and "name" in provenance.metadata:
            return provenance.metadata["name"]

        # Use a title if available in metadata
        if provenance.metadata and "title" in provenance.metadata:
            return provenance.metadata["title"]

        # Create a label based on data type and creation time
        creation_date = datetime.datetime.fromisoformat(provenance.creation_time).strftime("%Y-%m-%d")
        return f"{provenance.data_type} ({creation_date})"

    def _format_lineage_as_dot(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
        """Format lineage visualization as DOT format for GraphViz."""
        dot_visualization = visualization.copy()
        dot_lines = []

        # Start the digraph
        dot_lines.append(f'digraph DataLineage {{')
        dot_lines.append('  rankdir=LR;')
        dot_lines.append('  node [shape=box, style=filled];')

        # Add nodes
        for node in visualization["nodes"]:
            node_id = node["id"]
            label = node["label"]
            node_type = node["type"]

            # Choose color based on node type
            color = self._get_node_color(node_type)

            # Add node with attributes
            dot_lines.append(f'  "{node_id}" [label="{label}", fillcolor="{color}"];')

        # Add edges
        for edge in visualization["edges"]:
            source = edge["source"]
            target = edge["target"]
            relationship = edge["relationship"]

            # Add edge with label
            dot_lines.append(f'  "{source}" -> "{target}" [label="{relationship}"];')

        # Close the graph
        dot_lines.append('}')

        # Join all DOT content
        dot_visualization["dot_content"] = "\n".join(dot_lines)
        return dot_visualization

    def _format_lineage_as_mermaid(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
        """Format lineage visualization as Mermaid flowchart."""
        mermaid_visualization = visualization.copy()
        mermaid_lines = []

        # Start the flowchart
        mermaid_lines.append('graph LR')

        # Add nodes
        for node in visualization["nodes"]:
            node_id = node["id"]
            label = node["label"]
            node_type = node["type"]

            # Use node type to determine style
            style = self._get_mermaid_node_style(node_type)

            # Add node with label - create safe ID by replacing special chars
            safe_id = f"node_{node_id.replace('-', '_')}"
            mermaid_lines.append(f'  {safe_id}["{label}"{style}]')

        # Add edges
        for edge in visualization["edges"]:
            source = edge["source"]
            target = edge["target"]
            relationship = edge["relationship"]

            # Create safe IDs for source and target
            safe_source = f"node_{source.replace('-', '_')}"
            safe_target = f"node_{target.replace('-', '_')}"

            # Add edge with label
            mermaid_lines.append(f'  {safe_source} -->|"{relationship}"| {safe_target}')

        # Join all Mermaid content
        mermaid_visualization["mermaid_content"] = "\n".join(mermaid_lines)
        return mermaid_visualization

    def _format_lineage_as_d3(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
        """Format lineage visualization for D3.js force-directed graph."""
        d3_visualization = visualization.copy()

        # Create D3 format (D3 expects nodes with unique ids and links with source/target indices)
        d3_nodes = []
        node_index_map = {}

        # Process nodes
        for i, node in enumerate(visualization["nodes"]):
            node_index_map[node["id"]] = i
            d3_node = {
                "id": node["id"],
                "label": node["label"],
                "type": node["type"],
                "group": self._get_node_group(node["type"])
            }

            # Add any additional attributes
            if "attributes" in node:
                d3_node["attributes"] = node["attributes"]

            d3_nodes.append(d3_node)

        # Process links (edges)
        d3_links = []
        for edge in visualization["edges"]:
            d3_link = {
                "source": node_index_map[edge["source"]],
                "target": node_index_map[edge["target"]],
                "relationship": edge["relationship"],
                "value": 1  # Default strength
            }

            # Add any additional attributes
            if "attributes" in edge:
                d3_link["attributes"] = edge["attributes"]

            d3_links.append(d3_link)

        # Add D3 specific formats
        d3_visualization["d3_data"] = {
            "nodes": d3_nodes,
            "links": d3_links
        }

        return d3_visualization

    def _get_node_color(self, node_type: str) -> str:
        """Helper to determine node color based on type for GraphViz."""
        type_colors = {
            "dataset": "#a1d99b",  # Green
            "model": "#9ecae1",    # Blue
            "index": "#bcbddc",    # Purple
            "embedding": "#fdae6b", # Orange
            "transformation": "#bdbdbd", # Gray
            "unknown": "#f7f7f7"   # Light gray
        }
        return type_colors.get(node_type.lower(), "#f7f7f7")

    def _get_mermaid_node_style(self, node_type: str) -> str:
        """Helper to determine node style based on type for Mermaid."""
        type_styles = {
            "dataset": ":::dataset",
            "model": ":::model",
            "index": ":::index",
            "embedding": ":::embedding",
            "transformation": ":::transformation",
            "unknown": ""
        }
        return type_styles.get(node_type.lower(), "")

    def _get_node_group(self, node_type: str) -> int:
        """Helper to determine node group (for coloring) based on type for D3."""
        type_groups = {
            "dataset": 1,
            "model": 2,
            "index": 3,
            "embedding": 4,
            "transformation": 5,
            "unknown": 0
        }
        return type_groups.get(node_type.lower(), 0)


def initialize_security(config: Optional[SecurityConfig] = None) -> SecurityManager:
    """
    Initialize the security manager.

    Args:
        config: Configuration for security features

    Returns:
        SecurityManager: The initialized security manager
    """
    return SecurityManager.initialize(config or SecurityConfig())


def get_security_manager() -> SecurityManager:
    """
    Get the security manager instance.

    Returns:
        SecurityManager: The security manager
    """
    return SecurityManager.get_instance()


def require_authentication(func):
    """
    Decorator to require authentication for a function.

    Args:
        func: Function to decorate

    Returns:
        Callable: Decorated function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        manager = get_security_manager()
        if not manager.current_user:
            manager.logger.warning("Authentication required")
            raise PermissionError("Authentication required")

        return func(*args, **kwargs)

    return wrapper


def require_access(resource_id_param: str, access_type: str):
    """
    Decorator to require access to a resource for a function.

    Args:
        resource_id_param: Name of the parameter containing the resource ID
        access_type: Type of access required (read, write, admin)

    Returns:
        Callable: Decorator function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get resource ID
            resource_id = None

            # Check if resource ID is in kwargs
            if resource_id_param in kwargs:
                resource_id = kwargs[resource_id_param]

            # Check if resource ID is in args
            elif args:
                # Get function signature
                import inspect
                sig = inspect.signature(func)
                parameters = list(sig.parameters.keys())

                # Find resource ID parameter index
                try:
                    param_index = parameters.index(resource_id_param)
                    if param_index < len(args):
                        resource_id = args[param_index]
                except ValueError:
                    pass

            if not resource_id:
                raise ValueError(f"Resource ID parameter '{resource_id_param}' not found")

            # Check access
            manager = get_security_manager()
            if not manager.check_access(resource_id, access_type):
                manager.logger.warning(f"Access denied to {resource_id} with {access_type} access")
                raise PermissionError(f"Access denied to {resource_id} with {access_type} access")

            return func(*args, **kwargs)

        return wrapper

    return decorator


@contextlib.contextmanager
def encrypted_context(data_or_file: Union[bytes, str, BinaryIO], key_id: Optional[str] = None):
    """
    Context manager for working with encrypted data.

    Args:
        data_or_file: Data or file to encrypt/decrypt
        key_id: ID of the key to use, or None to generate a new key

    Yields:
        tuple: (decrypted_data, encryption_key_id)
    """
    manager = get_security_manager()

    # Determine if we have data or a file
    is_file = hasattr(data_or_file, 'read') or (isinstance(data_or_file, str) and os.path.exists(data_or_file))
    is_already_encrypted = False

    try:
        if is_file:
            # Handle file
            if hasattr(data_or_file, 'read'):
                # File-like object
                original_position = data_or_file.tell()
                file_data = data_or_file.read()
                data_or_file.seek(original_position)
            else:
                # File path
                with open(data_or_file, 'rb') as f:
                    file_data = f.read()

            # Check if file is already encrypted
            # In a real implementation, we would have a way to detect this
            is_already_encrypted = False

            if is_already_encrypted:
                # Decrypt existing file
                file_key_id = "unknown"  # In a real implementation, we would extract this
                decrypted_data = manager.decrypt_data(file_data, file_key_id)
                used_key_id = file_key_id
            else:
                # Use as-is
                decrypted_data = file_data
                # Generate key if needed
                used_key_id = key_id or manager.generate_encryption_key()
        else:
            # Handle raw data
            if isinstance(data_or_file, str):
                data = data_or_file.encode()
            else:
                data = data_or_file

            # Assume data is not encrypted
            decrypted_data = data
            # Generate key if needed
            used_key_id = key_id or manager.generate_encryption_key()

        # Yield the decrypted data and key ID
        yield decrypted_data, used_key_id

    finally:
        # We don't automatically re-encrypt here, the caller needs to do that
        # if desired using the key ID we provided
        pass


if __name__ == "__main__":
    # Example usage
    print("Security and Governance Module for IPFS Datasets")

    if not CRYPTOGRAPHY_AVAILABLE:
        print("Warning: cryptography module not available. Install with: pip install cryptography")

    if not UCAN_AVAILABLE:
        print("Warning: UCAN module not available. Make sure ucan.py is in the same directory.")

    # Initialize security manager with UCAN support
    config = SecurityConfig(
        enabled=True,
        encryption_algorithm="AES-256",
        log_all_access=True,
        track_provenance=True,
        use_ucan=UCAN_AVAILABLE
    )

    security = initialize_security(config)

    # Create a test user
    security.create_user("testuser", "password123", access_level="admin")

    # Authenticate
    success = security.authenticate_user("testuser", "password123")
    print(f"Authentication {'succeeded' if success else 'failed'}")

    # Create encryption key with UCAN capabilities
    key_id = security.generate_encryption_key()
    print(f"Generated key: {key_id}")

    key = security.encryption_keys[key_id]
    if key.ucan_did:
        print(f"Key DID: {key.ucan_did}")

        # Create a second DID for delegation testing
        if security.ucan_manager:
            bob_keypair = security.ucan_manager.generate_keypair()
            print(f"Generated keypair for Bob: {bob_keypair.did}")

            # Delegate encrypt capability to Bob
            token_id = security.delegate_encryption_capability(
                key_id=key_id,
                delegator_did=key.ucan_did,
                delegatee_did=bob_keypair.did,
                action="encrypt",
                caveats={"max_uses": 5}
            )

            if token_id:
                print(f"Delegated encrypt capability to Bob: {token_id}")

                # Verify Bob has the capability
                has_cap = security.ucan_manager.has_capability(bob_keypair.did, key_id, "encrypt")
                print(f"Bob has encrypt capability: {has_cap}")

                # Test encryption with Bob's capability
                test_data = "This is a test of the encryption system".encode()
                encrypted_data, metadata = security.encrypt_data(test_data, key_id, bob_keypair.did)
                print(f"Encrypted data with Bob's capability: {len(encrypted_data)} bytes")
                print(f"Metadata: {metadata}")

                # Revoke Bob's capability
                revoked = security.revoke_encryption_capability(token_id, key.ucan_did, "No longer needed")
                print(f"Revoked Bob's encrypt capability: {revoked}")

                # Check if capability is revoked
                has_cap = security.ucan_manager.has_capability(bob_keypair.did, key_id, "encrypt")
                print(f"Bob has encrypt capability after revocation: {has_cap}")

    # Standard encryption operations
    print("\nStandard Encryption Operations:")
    test_data = "This is a test of the encryption system".encode()
    encrypted_data, metadata = security.encrypt_data(test_data, key_id)
    print(f"Encrypted data: {len(encrypted_data)} bytes")
    print(f"Metadata: {metadata}")

    decrypted_data = security.decrypt_data(encrypted_data, key_id)
    print(f"Decrypted data: {decrypted_data.decode()}")

    # Create resource policy
    policy = security.create_resource_policy("test-resource-1", "dataset")
    print(f"Created policy for {policy.resource_id} with owner {policy.owner}")

    # Test access
    has_access = security.check_access("test-resource-1", "read")
    print(f"User has read access: {has_access}")

    # Record provenance
    provenance = security.record_provenance(
        data_id="test-data-1",
        source="test",
        process_steps=[{"name": "test-step", "timestamp": datetime.datetime.now().isoformat()}],
        parent_ids=[],
        checksum="12345",
        metadata={"test": "value"}
    )
    print(f"Recorded provenance for {provenance.data_id} from {provenance.source}")

    # Get audit logs
    logs = security.get_audit_logs(limit=5)
    print(f"Retrieved {len(logs)} audit log entries")
    for log in logs:
        print(f"  {log.timestamp} - {log.event_type} - {log.user} - {log.action}")
