"""
UCAN (User Controlled Authorization Networks) Mock Implementation.

This module provides a basic implementation of UCAN for capability-based authorization,
focusing on encryption key delegation and management. This is a simplified mock version
for demonstration purposes.

UCANs allow for capability-based delegation of permissions, where one principal
can delegate a subset of their capabilities to another principal.
"""

import os
import json
import time
import base64
import hashlib
import uuid
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
import datetime
import jwt  # For JSON Web Token handling

# For encryption and signature verification
try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding, utils
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
    from cryptography.exceptions import InvalidSignature
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

# Constants
DEFAULT_UCAN_DIR = os.path.expanduser("~/.ipfs_datasets/ucan")
DEFAULT_KEY_SIZE = 2048
DEFAULT_TTL = 3600  # 1 hour
SUPPORTED_CAPABILITIES = [
    "encrypt",    # Can encrypt data
    "decrypt",    # Can decrypt data
    "delegate",   # Can delegate capabilities to others
    "revoke",     # Can revoke capabilities
    "manage"      # Can manage keys (create, delete, etc.)
]


@dataclass
class UCANKeyPair:
    """
    A key pair for UCAN (User Controlled Authorization Networks) authentication and signing.

    This class represents a cryptographic key pair used for UCAN-based authentication,
    containing both public and private key components in PEM format along with associated
    metadata for decentralized identity management.

    Attributes:
        did (str): Decentralized Identifier (DID) that uniquely identifies the key pair
            in the decentralized web. Format typically follows DID specification.
        public_key_pem (str): Public key encoded in PEM (Privacy-Enhanced Mail) format.
            Used for signature verification and encryption operations.
        private_key_pem (Optional[str]): Private key encoded in PEM format. Set to None
            for public-only key pairs where private key operations are not needed.
            Defaults to None for security purposes.
        created_at (str): ISO 8601 formatted timestamp indicating when the key pair
            was created. Automatically set to current datetime if not provided.
        key_type (str): The cryptographic algorithm type used for the key pair.
            Defaults to "RSA". Other supported types may include "Ed25519" or "secp256k1".

    Example:
        >>> keypair = UCANKeyPair(
        ...     did="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        ...     public_key_pem="-----BEGIN PUBLIC KEY-----\\n...",
        ...     private_key_pem="-----BEGIN PRIVATE KEY-----\\n..."
        ... )

    Note:
        Private keys should be handled with extreme care and stored securely.
        Consider using environment variables or secure key management systems
        for production deployments.
    """
    did: str  # Decentralized Identifier (DID)
    public_key_pem: str
    private_key_pem: Optional[str] = None  # None for public-only keys
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    key_type: str = "RSA"


@dataclass
class UCANCapability:
    """
    Represents a capability within a User Controlled Authorization Network (UCAN) token.

    A UCANCapability defines a specific permission that can be granted, specifying what
    resource can be accessed, what action can be performed on that resource, and any
    additional restrictions or conditions that apply.

    Attributes:
        resource (str): The URI or identifier of the resource this capability grants
                       access to. This could be a specific file, directory, service
                       endpoint, or any other addressable resource.
        action (str): The specific action or operation that this capability permits
                     on the resource. Common actions include 'encrypt', 'decrypt',
                     'read', 'write', 'delete', 'delegate', or custom domain-specific
                     operations.
        caveats (Dict[str, Any]): Additional restrictions, conditions, or metadata
                                 that constrain how this capability can be used.
                                 Examples include time-based expiration, rate limits,
                                 IP restrictions, or other contextual constraints.
                                 Defaults to an empty dictionary if no caveats apply.

    Example:
        >>> capability = UCANCapability(
        ...     resource="ipfs://QmExample123",
        ...     action="read",
        ...     caveats={"expires_at": "2024-12-31T23:59:59Z"}
        ... )
    """
    resource: str  # What resource this capability applies to
    action: str  # What action this capability allows (encrypt, decrypt, delegate, etc.)
    caveats: Dict[str, Any] = field(default_factory=dict)  # Restrictions on the capability


@dataclass
class UCANToken:
    """
    User Controlled Authorization Network (UCAN) token for decentralized authorization.

    A UCAN token represents a cryptographically verifiable authorization credential
    that allows delegation of capabilities between decentralized identities (DIDs).
    The token contains information about what actions are authorized, who can perform
    them, and when the authorization is valid.

    Attributes:
        token_id (str): Unique identifier for this UCAN token.
        issuer (str): Decentralized identifier (DID) of the entity issuing this token.
        audience (str): Decentralized identifier (DID) of the entity receiving authorization.
        capabilities (List[UCANCapability]): List of specific capabilities or permissions
            granted by this token.
        expires_at (str): ISO 8601 timestamp indicating when this token expires.
        not_before (str): ISO 8601 timestamp indicating when this token becomes valid.
        proof (Optional[str]): Cryptographic proof of delegation chain, if this token
            was delegated from another UCAN. None for root tokens.
        signature (Optional[str]): Cryptographic signature of the token content,
            used to verify authenticity and integrity.

    Note:
        UCAN tokens follow the UCAN specification for decentralized authorization.
        They can be chained together to create delegation hierarchies where
        capabilities can be passed down from one entity to another with proper
        cryptographic verification.
    """
    token_id: str
    issuer: str  # DID of the issuer
    audience: str  # DID of the audience
    capabilities: List[UCANCapability]
    expires_at: str
    not_before: str
    proof: Optional[str] = None  # Signed proof of delegation
    signature: Optional[str] = None  # Token signature


@dataclass
class UCANRevocation:
    """
    Represents a revocation of a UCAN (User Controlled Authorization Network) token.

    A UCAN revocation is used to invalidate a previously issued UCAN token,
    effectively removing its authorization capabilities. This is crucial for
    security scenarios where tokens need to be revoked due to compromise,
    expiration, or other security concerns.

    Attributes:
        token_id (str): Unique identifier of the UCAN token being revoked.
        revoked_by (str): Decentralized Identifier (DID) of the entity that 
                         initiated the revocation. This should be an authorized
                         party capable of revoking the token.
        revoked_at (str): ISO 8601 timestamp indicating when the revocation
                         occurred. Should be in UTC format for consistency.
        reason (str): Human-readable explanation for why the token was revoked.
                     Common reasons include 'compromised', 'expired', 'replaced',
                     or 'policy_violation'.

    Example:
        >>> revocation = UCANRevocation(
        ...     token_id="ucan_abc123",
        ...     revoked_by="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        ...     revoked_at="2023-12-01T10:30:00Z",
        ...     reason="Token compromised"
        ... )

    Note:
        This class follows the UCAN specification for token revocation.
        The revoked_by DID must have appropriate authority to revoke the token.
    """
    token_id: str
    revoked_by: str  # DID of the revoker
    revoked_at: str
    reason: str


class UCANManager:
    """
    Comprehensive manager for UCAN (User Controlled Authorization Networks) operations.
    
    The UCANManager class provides a complete implementation for managing decentralized
    authorization through cryptographically verifiable capability tokens. It handles
    the full lifecycle of UCAN operations including keypair management, token creation,
    verification, delegation, and revocation.
    
    This manager implements the UCAN specification for capability-based authorization,
    enabling secure delegation of permissions between decentralized identities (DIDs)
    without requiring a central authority. Each operation is cryptographically secured
    and maintains an immutable audit trail.
    
    Key Features:
    - **Keypair Management**: Generate, import, and store RSA keypairs with DIDs
    - **Token Lifecycle**: Create, verify, delegate, and revoke UCAN tokens
    - **Capability Control**: Fine-grained resource and action permissions
    - **Delegation Chains**: Secure capability inheritance with cryptographic proof
    - **Revocation Support**: Immediate token invalidation with audit trails
    - **Persistent Storage**: Automatic persistence of keypairs, tokens, and revocations
    - **Cryptographic Security**: RS256 signatures for token integrity
    
    Supported Capabilities:
    - encrypt: Permission to encrypt data or resources
    - decrypt: Permission to decrypt data or resources  
    - delegate: Permission to delegate capabilities to others
    - revoke: Permission to revoke previously granted capabilities
    - manage: Permission to manage keys and system operations
    
    Storage Structure:
    The manager maintains persistent storage in ~/.ipfs_datasets/ucan/:
    - keypairs.json: RSA keypairs with DIDs and metadata
    - tokens.json: Active UCAN tokens with capabilities and signatures
    - revocations.json: Revoked token registry with timestamps and reasons

    Example:
        >>> manager = UCANManager.get_instance()
        >>> manager.initialize()
        >>> alice = manager.generate_keypair()
        >>> bob = manager.generate_keypair()
        >>> 
        >>> capability = UCANCapability("file://secret.txt", "read")
        >>> token = manager.create_token(
        ...     issuer_did=alice.did,
        ...     audience_did=bob.did,
        ...     capabilities=[capability]
        ... )
        >>> 
        >>> is_valid, error = manager.verify_token(token.token_id)
        >>> has_access = manager.has_capability(bob.did, "file://secret.txt", "read")
    """

    _instance = None

    @classmethod
    def get_instance(cls) -> 'UCANManager':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """Initialize the UCAN (User Controlled Authorization Networks) manager.

        Sets up the internal state for managing UCAN tokens, keypairs, and revocations.
        Creates the default UCAN directory structure if it doesn't already exist.

        Attributes:
            keypairs (dict): Storage for cryptographic keypairs used in UCAN operations
            tokens (dict): Cache of active UCAN tokens
            revocations (dict): Registry of revoked UCAN tokens
            initialized (bool): Flag indicating whether the manager has been properly initialized

        Note:
            The UCAN directory will be created at the default location if it doesn't exist,
            ensuring proper file system structure for token storage and management.
        """
        self.keypairs = {}
        self.tokens = {}
        self.revocations = {}
        self.initialized = False

        # Create UCAN directory if needed
        if not os.path.exists(DEFAULT_UCAN_DIR):
            os.makedirs(DEFAULT_UCAN_DIR, exist_ok=True)

    def initialize(self) -> bool:
        """
        Initialize the UCAN (User Controlled Authorization Networks) manager.
        
        This method performs the complete initialization sequence for the UCAN manager,
        including loading cryptographic keypairs, authentication tokens, and revocation
        lists. The initialization process requires the cryptography module to be available.
        
        The initialization process includes:
        - Verification of cryptography module availability
        - Loading and validating stored keypairs
        - Loading existing authentication tokens
        - Loading token revocation lists
        - Setting the manager's initialized state
        
            bool: True if initialization completed successfully, False if the 
                  cryptography module is unavailable or initialization fails.
                  
        Note:
            If the cryptography module is not available, a warning will be printed
            and the method will return False without attempting initialization.
            
        Raises:
            This method handles exceptions internally and returns False on failure
            rather than propagating exceptions.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            print("Warning: cryptography module not available, cannot initialize UCAN")
            return False

        # Load keypairs
        self._load_keypairs()

        # Load tokens
        self._load_tokens()

        # Load revocations
        self._load_revocations()

        self.initialized = True
        return True

    def _load_keypairs(self) -> None:
        """Load cryptographic keypairs from persistent storage.
        
        Reads keypair data from the default UCAN directory's keypairs.json file
        and reconstructs UCANKeyPair objects with their associated metadata.
        
        The method handles missing files gracefully and provides error handling
        for corrupted or invalid keypair data. Successfully loaded keypairs are
        stored in the instance's keypairs dictionary, indexed by their DID.
        
        File Format:
            The keypairs.json file should contain a JSON object where:
            - Keys are DID strings
            - Values are objects containing:
                - public_key_pem (str): PEM-encoded public key
                - private_key_pem (str, optional): PEM-encoded private key
                - created_at (str, optional): ISO format timestamp
                - key_type (str, optional): Key algorithm type, defaults to "RSA"
        
        Side Effects:
            - Populates self.keypairs dictionary with loaded UCANKeyPair objects
            - Prints status messages to stdout
            - Handles file I/O exceptions gracefully
        
        Raises:
            Does not raise exceptions - errors are caught and logged to stdout.
        """
        keypairs_file = os.path.join(DEFAULT_UCAN_DIR, "keypairs.json")
        if os.path.exists(keypairs_file):
            try:
                with open(keypairs_file, 'r') as f:
                    keypair_data = json.load(f)

                self.keypairs = {}
                for did, data in keypair_data.items():
                    self.keypairs[did] = UCANKeyPair(
                        did=did,
                        public_key_pem=data["public_key_pem"],
                        private_key_pem=data.get("private_key_pem"),
                        created_at=data.get("created_at", datetime.datetime.now().isoformat()),
                        key_type=data.get("key_type", "RSA")
                    )

                print(f"Loaded {len(self.keypairs)} keypairs from storage")
            except Exception as e:
                print(f"Error loading keypairs: {str(e)}")

    def _save_keypairs(self) -> None:
        """Save all keypairs to persistent storage as JSON.
        
        Serializes the current keypairs dictionary to a JSON file located at
        {DEFAULT_UCAN_DIR}/keypairs.json. Each keypair is stored with its DID
        as the key and includes public key PEM, private key PEM, creation timestamp,
        and key type.
        
        The method handles serialization of KeyPair objects by extracting their
        attributes into a dictionary format suitable for JSON storage.
        
        Raises:
            Exception: If file writing fails or serialization encounters an error.
            The error is caught and logged but not re-raised.
            
        Side Effects:
            - Creates or overwrites the keypairs.json file
            - Prints success message with count of saved keypairs
            - Prints error message if save operation fails
        
        Note:
            This is a private method intended for internal storage management.
            The keypairs file contains sensitive cryptographic material and should
            be protected with appropriate file system permissions.
        """
        keypairs_file = os.path.join(DEFAULT_UCAN_DIR, "keypairs.json")
        try:
            # Convert keypairs to serializable dictionary
            keypair_data = {}
            for did, keypair in self.keypairs.items():
                keypair_data[did] = {
                    "public_key_pem": keypair.public_key_pem,
                    "private_key_pem": keypair.private_key_pem,
                    "created_at": keypair.created_at,
                    "key_type": keypair.key_type
                }

            with open(keypairs_file, 'w') as f:
                json.dump(keypair_data, f, indent=2)

            print(f"Saved {len(self.keypairs)} keypairs to storage")
        except Exception as e:
            print(f"Error saving keypairs: {str(e)}")

    def _load_tokens(self) -> None:
        """Load UCAN tokens from persistent storage.
        
        Reads token data from the tokens.json file in the default UCAN directory
        and reconstructs UCANToken objects with their associated capabilities.
        Each token contains issuer/audience information, capabilities with 
        resources/actions/caveats, expiration times, and cryptographic proofs.
        
        The method populates the self.tokens dictionary with token_id as keys
        and UCANToken instances as values. If the tokens file doesn't exist,
        the method completes silently. Loading errors are caught and reported
        but don't raise exceptions.
        
        Side Effects:
            - Modifies self.tokens dictionary
            - Prints loading status to stdout
            - Prints error messages on failure
            
        File Format:
            Expected JSON structure with token_id keys mapping to objects
            containing issuer, audience, capabilities array, expires_at,
            not_before, and optional proof/signature fields.
        """
        tokens_file = os.path.join(DEFAULT_UCAN_DIR, "tokens.json")
        if os.path.exists(tokens_file):
            try:
                with open(tokens_file, 'r') as f:
                    token_data = json.load(f)

                self.tokens = {}
                for token_id, data in token_data.items():
                    capabilities = []
                    for cap_data in data["capabilities"]:
                        capabilities.append(UCANCapability(
                            resource=cap_data["resource"],
                            action=cap_data["action"],
                            caveats=cap_data.get("caveats", {})
                        ))

                    self.tokens[token_id] = UCANToken(
                        token_id=token_id,
                        issuer=data["issuer"],
                        audience=data["audience"],
                        capabilities=capabilities,
                        expires_at=data["expires_at"],
                        not_before=data["not_before"],
                        proof=data.get("proof"),
                        signature=data.get("signature")
                    )

                print(f"Loaded {len(self.tokens)} tokens from storage")
            except Exception as e:
                print(f"Error loading tokens: {str(e)}")

    def _save_tokens(self) -> None:
        """Save UCAN tokens to persistent JSON storage.
        
        Serializes all tokens in the token cache to a JSON file in the default
        UCAN directory. Each token is converted to a dictionary containing its
        issuer, audience, capabilities, expiration times, proof, and signature.
        
        The tokens are saved to `{DEFAULT_UCAN_DIR}/tokens.json` with pretty
        printing (2-space indentation) for readability.
        
        Raises:
            Exception: If there's an error creating the directory, opening the file,
                      or writing the JSON data. Error details are printed to stdout.
        
        Note:
            This is a private method intended for internal token persistence.
            Capabilities are flattened to dictionaries containing resource, action,
            and caveats fields for JSON serialization compatibility.
        """
        tokens_file = os.path.join(DEFAULT_UCAN_DIR, "tokens.json")
        try:
            # Convert tokens to serializable dictionary
            token_data = {}
            for token_id, token in self.tokens.items():
                capabilities = []
                for cap in token.capabilities:
                    capabilities.append({
                        "resource": cap.resource,
                        "action": cap.action,
                        "caveats": cap.caveats
                    })

                token_data[token_id] = {
                    "issuer": token.issuer,
                    "audience": token.audience,
                    "capabilities": capabilities,
                    "expires_at": token.expires_at,
                    "not_before": token.not_before,
                    "proof": token.proof,
                    "signature": token.signature
                }

            with open(tokens_file, 'w') as f:
                json.dump(token_data, f, indent=2)

            print(f"Saved {len(self.tokens)} tokens to storage")
        except Exception as e:
            print(f"Error saving tokens: {str(e)}")

    def _load_revocations(self) -> None:
        """Load revocations from persistent storage.

        Reads revocation data from the revocations.json file in the default UCAN directory
        and reconstructs UCANRevocation objects. If the file doesn't exist, the method
        returns silently without error. Any JSON parsing or file reading errors are caught
        and logged to stdout.

        The revocations are stored in the instance's revocations dictionary, keyed by
        token_id. Each revocation contains metadata about when and why a UCAN token
        was revoked, along with the identity of the revoking party.

        Raises:
            None: Errors are caught and logged rather than propagated.

        Side Effects:
            - Updates self.revocations dictionary with loaded data
            - Prints status messages to stdout (success count or error details)
            - Creates UCANRevocation objects from stored JSON data

        Note:
            Expected JSON structure for each revocation entry:
            {
                "token_id": {
                    "revoked_by": str,
                    "revoked_at": str/timestamp,
                    "reason": str
                }
            }
        """
        revocations_file = os.path.join(DEFAULT_UCAN_DIR, "revocations.json")
        if os.path.exists(revocations_file):
            try:
                with open(revocations_file, 'r') as f:
                    revocation_data = json.load(f)

                self.revocations = {}
                for token_id, data in revocation_data.items():
                    self.revocations[token_id] = UCANRevocation(
                        token_id=token_id,
                        revoked_by=data["revoked_by"],
                        revoked_at=data["revoked_at"],
                        reason=data["reason"]
                    )

                print(f"Loaded {len(self.revocations)} revocations from storage")
            except Exception as e:
                print(f"Error loading revocations: {str(e)}")


    def _save_revocations(self) -> None:
        """Save UCAN token revocations to persistent storage.
        
        Serializes the current revocations dictionary to a JSON file in the default
        UCAN directory. Each revocation entry is converted from a dataclass to a
        dictionary format for JSON serialization.
        
        The revocations are saved to '{DEFAULT_UCAN_DIR}/revocations.json' with
        pretty-printed formatting (2-space indentation).
        
        Raises:
            Exception: If file writing fails due to permissions, disk space, or
                      serialization errors. Error details are printed to stdout.
        
        Note:
            This is a private method intended for internal use by the UCAN manager.
            Revocations are automatically saved when modified through public methods.
        """
        revocations_file = os.path.join(DEFAULT_UCAN_DIR, "revocations.json")
        try:
            # Convert revocations to serializable dictionary
            revocation_data = {}
            for token_id, revocation in self.revocations.items():
                revocation_data[token_id] = asdict(revocation)

            with open(revocations_file, 'w') as f:
                json.dump(revocation_data, f, indent=2)

            print(f"Saved {len(self.revocations)} revocations to storage")
        except Exception as e:
            print(f"Error saving revocations: {str(e)}")

    def generate_keypair(self) -> UCANKeyPair:
        """
        Generate a new RSA keypair for UCAN authentication and authorization.

        This method creates a 2048-bit RSA keypair using the cryptography library,
        serializes the keys to PEM format, generates a DID (Decentralized Identifier)
        from the public key fingerprint, and stores the keypair for future use.

            UCANKeyPair: A new keypair containing:
                - did: Decentralized identifier in format "did:key:{fingerprint}"
                - public_key_pem: RSA public key in PEM format
                - private_key_pem: RSA private key in PEM format (unencrypted)

        Raises:
            RuntimeError: If the UCAN manager is not initialized or if the
                         cryptography module is not available.

        Note:
            - The generated keypair is automatically stored in the manager's
              keypair storage and persisted to disk
            - Uses RSA with 2048-bit key size and public exponent 65537
            - Private keys are stored unencrypted in PEM format
            - DID is generated using SHA-256 hash of the public key PEM

        Example:
            >>> keypair = ucan_manager.generate_keypair()
            >>> print(keypair.did)
            did:key:a1b2c3d4e5f6...
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        if not CRYPTOGRAPHY_AVAILABLE:
            raise RuntimeError("Cryptography module not available")

        # Generate RSA keypair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=DEFAULT_KEY_SIZE,
            backend=default_backend()
        )

        # Extract public key
        public_key = private_key.public_key()

        # Serialize keys to PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        # Generate DID
        key_fingerprint = hashlib.sha256(public_pem.encode()).hexdigest()
        did = f"did:key:{key_fingerprint}"

        # Create keypair
        keypair = UCANKeyPair(
            did=did,
            public_key_pem=public_pem,
            private_key_pem=private_pem
        )

        # Store keypair
        self.keypairs[did] = keypair
        self._save_keypairs()

        return keypair

    def import_keypair(self, public_key_pem: str, private_key_pem: Optional[str] = None) -> UCANKeyPair:
        """
        Import an existing cryptographic keypair into the UCAN manager.
        
        This method allows you to import previously generated keypairs for use in UCAN
        operations. The keypair is stored internally and can be retrieved using the
        generated DID identifier.
        
        Args:
            public_key_pem (str): PEM-encoded public key string. Must be a valid
                PEM format public key.
            private_key_pem (Optional[str], optional): PEM-encoded private key string.
                If not provided, only signing operations requiring the private key
                will be unavailable. Defaults to None.
        
        Returns:
            UCANKeyPair: The imported keypair object containing the DID identifier
                and key material.
        
        Raises:
            RuntimeError: If the UCAN manager is not initialized or if the
                cryptography module is not available.
            ValueError: If the provided PEM keys are invalid or malformed.
        
        Example:
            >>> public_pem = "-----BEGIN PUBLIC KEY-----\n..."
            >>> private_pem = "-----BEGIN PRIVATE KEY-----\n..."
            >>> keypair = ucan_manager.import_keypair(public_pem, private_pem)
            >>> print(keypair.did)
            did:key:abc123...
        
        Note:
            The DID is generated by hashing the public key PEM content with SHA-256.
            The keypair is automatically saved to persistent storage.
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        if not CRYPTOGRAPHY_AVAILABLE:
            raise RuntimeError("Cryptography module not available")

        # Generate DID from public key
        key_fingerprint = hashlib.sha256(public_key_pem.encode()).hexdigest()
        did = f"did:key:{key_fingerprint}"

        # Create keypair
        keypair = UCANKeyPair(
            did=did,
            public_key_pem=public_key_pem,
            private_key_pem=private_key_pem
        )

        # Store keypair
        self.keypairs[did] = keypair
        self._save_keypairs()

        return keypair

    def get_keypair(self, did: str) -> Optional[UCANKeyPair]:
        """
        Retrieve a cryptographic keypair associated with a specific DID.

        This method looks up and returns a UCAN keypair from the manager's 
        internal storage based on the provided Decentralized Identifier (DID).
        The manager must be initialized before calling this method.

            did (str): The Decentralized Identifier (DID) string used as the 
                       lookup key for the desired keypair.

            Optional[UCANKeyPair]: The UCAN keypair object associated with the 
                                  provided DID, or None if no keypair is found 
                                  for the given DID.

        Raises:
            RuntimeError: If the UCAN manager has not been initialized prior 
                         to calling this method.

        Example:
            >>> keypair = ucan_manager.get_keypair("did:key:z6Mkhasd...")
            >>> if keypair:
            ...     print(f"Found keypair for DID: {keypair.did}")
            ... else:
            ...     print("Keypair not found")
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        return self.keypairs.get(did)

    def create_token(self, issuer_did: str, audience_did: str, capabilities: List[UCANCapability],
                    ttl: int = DEFAULT_TTL, not_before: Optional[str] = None,
                    proof: Optional[str] = None) -> UCANToken:
        """
        Create a new UCAN (User Controlled Authorization Network) token for decentralized authorization.

        This method creates a cryptographically signed UCAN token that grants specific capabilities
        from an issuer to an audience. The token follows the UCAN specification for capability-based
        authorization.

        The created token includes:
        - Cryptographic proof of issuer identity through digital signatures
        - Capability grants specifying what resources and actions are authorized
        - Temporal constraints (expiration and not-before times)
        - Optional delegation proof for capability inheritance
        - Unique token identifier for tracking and revocation

        Args:
            issuer_did (str): Decentralized Identifier (DID) of the entity issuing the token.
            Must exist in the keypair store and have an associated private key for signing.
            audience_did (str): Decentralized Identifier (DID) of the entity receiving the 
            authorization. Must exist in the keypair store.
            capabilities (List[UCANCapability]): List of specific capabilities being granted.
            Each capability defines a resource, action, and optional caveats that constrain
            usage. All capability actions must be from SUPPORTED_CAPABILITIES.
            ttl (int, optional): Time-to-live in seconds from creation time. Determines when
            the token expires. Defaults to DEFAULT_TTL (3600 seconds).
            not_before (Optional[str], optional): ISO 8601 timestamp before which the token
            is not valid. If None, the token is valid immediately. Defaults to None.
            proof (Optional[str], optional): Token ID of a parent UCAN token that proves
            the issuer has delegation rights for the granted capabilities. Required
            when creating derived tokens in a delegation chain. Defaults to None.

        Returns:
            UCANToken: A fully formed UCAN token containing the granted capabilities,
            cryptographic signature, and all necessary metadata for verification.

        Raises:
            RuntimeError: If the UCAN manager is not initialized.
            ValueError: If the issuer DID is not found, lacks a private key, the audience
            DID is not found, or any capability action is not supported.

        Example:
            >>> capability = UCANCapability(
            ...     resource="ipfs://QmExample",
            ...     action="read",
            ...     caveats={"max_uses": 10}
            ... )
            >>> token = manager.create_token(
            ...     issuer_did="did:key:alice123",
            ...     audience_did="did:key:bob456", 
            ...     capabilities=[capability],
            ...     ttl=7200,
            ...     proof="parent-token-id"
            ... )

        Note:
            The token is automatically stored in the manager's token cache and persisted
            to disk. Token signatures use RS256 (RSA with SHA-256) for cryptographic
            verification. If a proof token is provided, it must be valid and grant
            delegation capabilities to the issuer.
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        # Check if issuer exists
        issuer = self.get_keypair(issuer_did)
        if not issuer:
            raise ValueError(f"Issuer {issuer_did} not found")

        # Check if issuer has private key
        if not issuer.private_key_pem:
            raise ValueError(f"Issuer {issuer_did} does not have a private key")

        # Check if audience exists
        audience = self.get_keypair(audience_did)
        if not audience:
            raise ValueError(f"Audience {audience_did} not found")

        # Check capabilities
        for capability in capabilities:
            if capability.action not in SUPPORTED_CAPABILITIES:
                raise ValueError(f"Unsupported capability action: {capability.action}")

        # Create token
        now = datetime.datetime.now()
        expires = now + datetime.timedelta(seconds=ttl)

        token_id = str(uuid.uuid4())
        token = UCANToken(
            token_id=token_id,
            issuer=issuer_did,
            audience=audience_did,
            capabilities=capabilities,
            expires_at=expires.isoformat(),
            not_before=not_before or now.isoformat(),
            proof=proof
        )

        # Create token payload
        payload = {
            "iss": issuer_did,
            "aud": audience_did,
            "exp": int(expires.timestamp()),
            "nbf": int(datetime.datetime.fromisoformat(token.not_before).timestamp()),
            "cap": [asdict(cap) for cap in capabilities],
            "jti": token_id
        }

        if proof:
            payload["prf"] = proof

        # Sign token
        private_key = serialization.load_pem_private_key(
            issuer.private_key_pem.encode(),
            password=None,
            backend=default_backend()
        )

        # Use JWT for simplicity in this mock implementation
        token.signature = jwt.encode(payload, issuer.private_key_pem, algorithm="RS256")

        # Store token
        self.tokens[token_id] = token
        self._save_tokens()

        return token

    def verify_token(self, token_id: str) -> Tuple[bool, Optional[str]]:
        """
        Verify the validity and authenticity of a UCAN token.

        This method performs comprehensive verification of a UCAN token, including
        cryptographic signature validation, temporal constraints, revocation status,
        and delegation chain integrity.

        Verification steps include:
        - Token existence and accessibility
        - Revocation status checking
        - Temporal validity (expiration and not-before times)
        - Issuer identity and keypair validation
        - Cryptographic signature verification
        - Delegation chain validation (if applicable)

        Args:
            token_id (str): Unique identifier of the UCAN token to verify.
            Must correspond to an existing token in the manager's storage.

        Returns:
            Tuple[bool, Optional[str]]: A tuple containing:
            - bool: True if the token is valid and passes all verification
              checks, False otherwise.
            - Optional[str]: Error message describing why verification failed,
              or None if the token is valid. Common error messages include
              "Token not found", "Token expired", "Token revoked", or
              "Signature verification failed".

        Raises:
            RuntimeError: If the UCAN manager is not initialized.

        Example:
            >>> is_valid, error = manager.verify_token("token_abc123")
            >>> if is_valid:
            ...     print("Token is valid and can be trusted")
            ... else:
            ...     print(f"Token verification failed: {error}")
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        # Check if token exists
        if token_id not in self.tokens:
            return False, "Token not found"

        token = self.tokens[token_id]

        # Check if token is revoked
        if token_id in self.revocations:
            revocation = self.revocations[token_id]
            return False, f"Token revoked by {revocation.revoked_by} at {revocation.revoked_at}: {revocation.reason}"

        # Check expiration
        now = datetime.datetime.now()
        if now > datetime.datetime.fromisoformat(token.expires_at):
            return False, "Token expired"

        # Check not-before time
        if now < datetime.datetime.fromisoformat(token.not_before):
            return False, "Token not yet valid"

        # Check issuer
        issuer = self.get_keypair(token.issuer)
        if not issuer:
            return False, f"Issuer {token.issuer} not found"

        # Verify signature
        try:
            # In a real implementation, we would verify the signature here
            # For this mock, we just check if signature exists
            if not token.signature:
                return False, "Token not signed"

            # If token has a proof, verify the proof token
            if token.proof:
                proof_valid, proof_error = self.verify_token(token.proof)
                if not proof_valid:
                    return False, f"Proof verification failed: {proof_error}"

                # Check if proof token delegates required capabilities
                proof_token = self.tokens[token.proof]

                # Check issuer of proof token is audience of this token
                if proof_token.audience != token.issuer:
                    return False, "Proof token audience does not match issuer"

                # Check if proof token has delegation capability
                has_delegate = False
                for cap in proof_token.capabilities:
                    if cap.action == "delegate":
                        has_delegate = True
                        break

                if not has_delegate:
                    return False, "Proof token does not have delegation capability"

            return True, None

        except Exception as e:
            return False, f"Signature verification failed: {str(e)}"

    def revoke_token(self, token_id: str, revoker_did: str, reason: str) -> bool:
        """
        Revoke a UCAN token by marking it as invalid.

        This method allows the issuer or audience of a UCAN token to revoke it,
        preventing its future use. The revocation is permanently recorded with
        a timestamp and reason for audit purposes.

            token_id (str): Unique identifier of the UCAN token to revoke
            revoker_did (str): Decentralized identifier (DID) of the entity 
                              requesting revocation. Must be either the token's 
                              issuer or audience
            reason (str): Human-readable explanation for the revocation
                         (e.g., "compromised", "expired", "no longer needed")

            bool: True if the token was successfully revoked, False if the token
                  doesn't exist or the revoker lacks permission

        Raises:
            RuntimeError: If the UCAN manager has not been initialized

        Example:
            >>> success = ucan_manager.revoke_token(
            ...     token_id="ucan_123456",
            ...     revoker_did="did:key:z6Mk...",
            ...     reason="Security breach detected"
            ... )
            >>> print(success)  # True if revocation succeeded
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        # Check if token exists
        if token_id not in self.tokens:
            return False

        token = self.tokens[token_id]

        # Check if revoker is issuer or audience
        if revoker_did != token.issuer and revoker_did != token.audience:
            return False

        # Create revocation
        revocation = UCANRevocation(
            token_id=token_id,
            revoked_by=revoker_did,
            revoked_at=datetime.datetime.now().isoformat(),
            reason=reason
        )

        # Store revocation
        self.revocations[token_id] = revocation
        self._save_revocations()

        return True

    def get_token(self, token_id: str) -> Optional[UCANToken]:
        """
        Retrieve a UCAN token by its unique identifier.

        This method looks up and returns a specific UCAN token from the manager's
        internal storage using the provided token ID. The method performs a simple
        dictionary lookup without any validation or verification of the token's
        current validity status.

        Args:
            token_id (str): The unique identifier of the UCAN token to retrieve.
                   Must be a valid UUID string that corresponds to an
                   existing token in the manager's storage.

        Returns:
            Optional[UCANToken]: The UCAN token object if found, containing all
                    token metadata including issuer, audience, capabilities,
                    expiration times, proof, and signature. Returns None
                    if no token exists with the specified ID.

        Raises:
            RuntimeError: If the UCAN manager has not been initialized prior
                 to calling this method.

        Example:
            >>> token = ucan_manager.get_token("550e8400-e29b-41d4-a716-446655440000")
            >>> if token:
            ...     print(f"Found token issued by {token.issuer} to {token.audience}")
            ... else:
            ...     print("Token not found")

        Note:
            This method only retrieves the token data and does not perform any
            validation checks such as expiration, revocation status, or signature
            verification. Use verify_token() to check token validity before use.
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        return self.tokens.get(token_id)

    def get_capabilities(self, did: str) -> List[UCANCapability]:
        """
        Get all capabilities granted to a DID.

        Args:
            did: DID to get capabilities for

        Returns:
            list: List of capabilities
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        capabilities = []

        # Find all valid tokens where the DID is the audience
        for token_id, token in self.tokens.items():
            if token.audience == did:
                # Verify token
                is_valid, _ = self.verify_token(token_id)
                if is_valid:
                    capabilities.extend(token.capabilities)

        return capabilities

    def has_capability(self, did: str, resource: str, action: str) -> bool:
        """
        Check if a DID has authorization for a specific resource and action.

        This method performs a comprehensive capability check by examining all valid
        UCAN tokens where the specified DID is the audience. It supports wildcard
        matching for both resources and actions, allowing for flexible permission
        schemes.

        The method checks for:
        - Exact resource and action matches
        - Wildcard resource matches (resource="*") with specific actions
        - Wildcard action matches (action="*") with specific resources  
        - Full wildcard matches (resource="*", action="*") for unrestricted access

        Args:
            did (str): Decentralized Identifier to check capabilities for. Must be
            a valid DID that exists in the system.
            resource (str): The resource identifier to check access for. Can be any
            string identifier such as file paths, URLs, or service endpoints.
            action (str): The specific action to check authorization for. Must be
            one of the supported capability actions (encrypt, decrypt, delegate,
            revoke, manage) or a wildcard "*".

        Returns:
            bool: True if the DID has the requested capability through any valid
            UCAN token, False if no matching capability is found or all
            matching tokens are invalid/expired.

        Raises:
            RuntimeError: If the UCAN manager has not been initialized.

        Example:
            >>> # Check specific capability
            >>> has_access = manager.has_capability(
            ...     "did:key:alice123",
            ...     "ipfs://QmExample",
            ...     "read"
            ... )
            >>> 
            >>> # Check with wildcard resource
            >>> has_admin = manager.has_capability(
            ...     "did:key:admin456", 
            ...     "*",
            ...     "manage"
            ... )
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        capabilities = self.get_capabilities(did)

        for capability in capabilities:
            if capability.resource == resource and capability.action == action:
                return True

            # Check for wildcard resources
            if capability.resource == "*" and capability.action == action:
                return True

            # Check for wildcard actions
            if capability.resource == resource and capability.action == "*":
                return True

            # Check for full wildcards
            if capability.resource == "*" and capability.action == "*":
                return True

        return False

    def delegate_capability(self, issuer_did: str, audience_did: str, resource: str,
                         action: str, caveats: Optional[Dict[str, Any]] = None,
                         ttl: int = DEFAULT_TTL) -> Optional[UCANToken]:
        """
        Delegate a specific capability from one DID to another through UCAN token creation.

        This method enables secure delegation of capabilities in a UCAN-based authorization
        system. The issuer must possess both the target capability and delegation rights
        for the specified resource to successfully create a delegation token.

        Args:
            issuer_did (str): Decentralized Identifier of the entity delegating the capability.
            Must have both the target capability and delegation rights.
            audience_did (str): Decentralized Identifier of the entity receiving the capability.
            Must exist in the system's keypair registry.
            resource (str): URI or identifier of the resource being granted access to.
            Can be any string such as file paths, encryption keys, or service endpoints.
            action (str): Specific action being delegated (e.g., 'encrypt', 'decrypt', 'read').
            Must be from SUPPORTED_CAPABILITIES list.
            caveats (Optional[Dict[str, Any]]): Additional constraints on capability usage.
            Common caveats include usage limits, IP restrictions, or time windows.
            Defaults to None (no additional restrictions).
            ttl (int): Time-to-live in seconds for the delegated capability.
            Token will expire this many seconds after creation. Defaults to DEFAULT_TTL.

        Returns:
            Optional[UCANToken]: The newly created UCAN token containing the delegated
            capability if delegation succeeds, None if the issuer lacks required
            permissions or delegation rights.

        Raises:
            RuntimeError: If the UCAN manager has not been initialized.

        Example:
            >>> # Delegate encryption capability with usage limit
            >>> token = manager.delegate_capability(
            ...     issuer_did="did:key:alice123",
            ...     audience_did="did:key:bob456",
            ...     resource="encryption-key-789",
            ...     action="encrypt",
            ...     caveats={"max_uses": 10, "expires_after": "2024-12-31"},
            ...     ttl=86400  # 24 hours
            ... )
            >>> if token:
            ...     print(f"Successfully delegated capability: {token.token_id}")
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")

        # Check if issuer has the capability
        if not self.has_capability(issuer_did, resource, action) and issuer_did != resource:
            # Exception: if the issuer is the resource, they can delegate it
            return None

        # Check if issuer has delegation capability
        if not self.has_capability(issuer_did, resource, "delegate") and issuer_did != resource:
            return None

        # Create capability
        capability = UCANCapability(
            resource=resource,
            action=action,
            caveats=caveats or {}
        )

        # Create token
        token = self.create_token(
            issuer_did=issuer_did,
            audience_did=audience_did,
            capabilities=[capability],
            ttl=ttl
        )

        return token


def initialize_ucan() -> UCANManager:
    """
    Initialize the UCAN manager.

    Returns:
        UCANManager: The initialized UCAN manager
    """
    manager = UCANManager.get_instance()
    manager.initialize()
    return manager


def get_ucan_manager() -> UCANManager:
    """
    Get the UCAN manager instance.

    Returns:
        UCANManager: The UCAN manager
    """
    return UCANManager.get_instance()



def ucan_demonstration():
    """
    Demonstrates the complete UCAN (User Controlled Authorization Networks) workflow.
    
    This function provides a comprehensive example of UCAN token lifecycle management,
    including keypair generation, token creation, verification, capability delegation,
    and token revocation. It showcases how UCAN enables decentralized authorization
    through cryptographic tokens that can be verified without central authority.
    
    The demonstration includes:
    
    1. **System Initialization**: Sets up the UCAN manager and checks for required
       cryptographic dependencies.
    
    2. **Keypair Generation**: Creates cryptographic keypairs for three users (Alice,
       Bob, and Charlie) with their corresponding Decentralized Identifiers (DIDs).
    
    3. **Token Creation**: Alice creates a UCAN token granting Bob encryption
       capabilities for a specific resource with time-based expiration.
    
    4. **Token Verification**: Validates the cryptographic integrity and validity
       of issued tokens using the UCAN verification protocol.
    
    5. **Capability Checking**: Demonstrates how to query whether a DID holder
       has specific permissions for resources and actions.
    
    6. **Delegation Chain**: Shows the full delegation process where:
       - Alice grants Bob delegation rights
       - Bob then delegates encryption capabilities to Charlie
       - Each step maintains cryptographic proof of authorization
    
    7. **Token Revocation**: Demonstrates how token issuers can revoke previously
       granted capabilities and how this affects token validity.
    
    **UCAN Concepts Demonstrated:**
    
    - **Decentralized Identity**: Each user has a cryptographic DID
    - **Capability-based Security**: Permissions are resource and action specific
    - **Cryptographic Verification**: All tokens are cryptographically signed
    - **Delegation Chains**: Capabilities can be safely delegated to third parties
    - **Temporal Constraints**: Tokens can have TTL and expiration caveats
    - **Usage Constraints**: Delegation can include usage limits and other caveats
    - **Revocation**: Tokens can be invalidated by their issuers
    
    **Security Features:**
    
    - All operations are cryptographically secured using public key cryptography
    - Token integrity is maintained through digital signatures
    - Delegation preserves the chain of trust from original issuer
    - Revocation is tamper-proof and immediately effective
    
    **Output:**
    
    Prints detailed information about each operation including:
    - Generated DIDs for each participant
    - Token IDs and their issuer/audience relationships
    - Verification results with success/failure status
    - Capability check results
    - Delegation operation outcomes
    - Revocation confirmation and subsequent verification failure
    
    **Requirements:**
    
    - cryptography module (optional but recommended for production use)
    - Properly initialized UCAN manager instance
    
    **Note:**
    
    This demonstration uses realistic examples with encryption capabilities,
    but the same patterns apply to any resource and action combinations
    (e.g., file access, API endpoints, database operations, etc.).
    """
    # Example usage
    print("UCAN (User Controlled Authorization Networks) Mock Implementation")

    if not CRYPTOGRAPHY_AVAILABLE:
        print("Warning: cryptography module not available. Install with: pip install cryptography")

    # Initialize UCAN manager
    manager = initialize_ucan()

    # Generate keypairs
    alice = manager.generate_keypair()
    print(f"Generated keypair for Alice: {alice.did}")

    bob = manager.generate_keypair()
    print(f"Generated keypair for Bob: {bob.did}")

    # Create a token from Alice to Bob
    encryption_capability = UCANCapability(
        resource="encryption-key-123",
        action="encrypt",
        caveats={"expiry": datetime.datetime.now().isoformat()}
    )

    token = manager.create_token(
        issuer_did=alice.did,
        audience_did=bob.did,
        capabilities=[encryption_capability],
        ttl=3600  # 1 hour
    )

    print(f"Created token {token.token_id} from {token.issuer} to {token.audience}")

    # Verify the token
    is_valid, error = manager.verify_token(token.token_id)
    print(f"Token verification: {'valid' if is_valid else 'invalid'} - {error or 'no error'}")

    # Check if Bob has the capability
    has_cap = manager.has_capability(bob.did, "encryption-key-123", "encrypt")
    print(f"Bob has encrypt capability: {has_cap}")

    # Bob delegates to Charlie
    charlie = manager.generate_keypair()
    print(f"Generated keypair for Charlie: {charlie.did}")

    # First, give Bob delegation capability
    delegation_capability = UCANCapability(
        resource="encryption-key-123",
        action="delegate"
    )

    delegate_token = manager.create_token(
        issuer_did=alice.did,
        audience_did=bob.did,
        capabilities=[delegation_capability],
        ttl=3600  # 1 hour
    )

    print(f"Created delegation token {delegate_token.token_id} from {delegate_token.issuer} to {delegate_token.audience}")

    # Now Bob can delegate to Charlie
    charlie_token = manager.delegate_capability(
        issuer_did=bob.did,
        audience_did=charlie.did,
        resource="encryption-key-123",
        action="encrypt",
        caveats={"max_uses": 5}
    )

    if charlie_token:
        print(f"Delegated encrypt capability to Charlie: {charlie_token.token_id}")

        # Verify Charlie's token
        is_valid, error = manager.verify_token(charlie_token.token_id)
        print(f"Charlie's token verification: {'valid' if is_valid else 'invalid'} - {error or 'no error'}")

        # Check if Charlie has the capability
        has_cap = manager.has_capability(charlie.did, "encryption-key-123", "encrypt")
        print(f"Charlie has encrypt capability: {has_cap}")
    else:
        print("Failed to delegate capability to Charlie")

    # Revoke Bob's token
    revoked = manager.revoke_token(token.token_id, alice.did, "No longer needed")
    print(f"Revoked Bob's token: {revoked}")

    # Verify the token again
    is_valid, error = manager.verify_token(token.token_id)
    print(f"Token verification after revocation: {'valid' if is_valid else 'invalid'} - {error or 'no error'}")


if __name__ == "__main__":
    ucan_demonstration()
