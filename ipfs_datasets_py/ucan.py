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
    """Key pair for UCAN authentication and signing."""
    did: str  # Decentralized Identifier (DID)
    public_key_pem: str
    private_key_pem: Optional[str] = None  # None for public-only keys
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    key_type: str = "RSA"


@dataclass
class UCANCapability:
    """Capability within a UCAN token."""
    resource: str  # What resource this capability applies to
    action: str  # What action this capability allows (encrypt, decrypt, delegate, etc.)
    caveats: Dict[str, Any] = field(default_factory=dict)  # Restrictions on the capability


@dataclass
class UCANToken:
    """UCAN token for authorization."""
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
    """Revocation of a UCAN token."""
    token_id: str
    revoked_by: str  # DID of the revoker
    revoked_at: str
    reason: str


class UCANManager:
    """Manager for UCAN operations."""
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'UCANManager':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the UCAN manager."""
        self.keypairs = {}
        self.tokens = {}
        self.revocations = {}
        self.initialized = False
        
        # Create UCAN directory if needed
        if not os.path.exists(DEFAULT_UCAN_DIR):
            os.makedirs(DEFAULT_UCAN_DIR, exist_ok=True)
    
    def initialize(self) -> bool:
        """
        Initialize the UCAN manager.
        
        Returns:
            bool: Whether initialization was successful
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
        """Load keypairs from storage."""
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
        """Save keypairs to storage."""
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
        """Load tokens from storage."""
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
        """Save tokens to storage."""
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
        """Load revocations from storage."""
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
        """Save revocations to storage."""
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
        Generate a new RSA keypair for UCAN.
        
        Returns:
            UCANKeyPair: The generated keypair
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
        Import an existing keypair.
        
        Args:
            public_key_pem: PEM-encoded public key
            private_key_pem: PEM-encoded private key (optional)
            
        Returns:
            UCANKeyPair: The imported keypair
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
        Get a keypair by DID.
        
        Args:
            did: DID of the keypair
            
        Returns:
            UCANKeyPair: The keypair, or None if not found
        """
        if not self.initialized:
            raise RuntimeError("UCAN manager not initialized")
        
        return self.keypairs.get(did)
    
    def create_token(self, issuer_did: str, audience_did: str, capabilities: List[UCANCapability], 
                    ttl: int = DEFAULT_TTL, not_before: Optional[str] = None, 
                    proof: Optional[str] = None) -> UCANToken:
        """
        Create a new UCAN token.
        
        Args:
            issuer_did: DID of the issuer
            audience_did: DID of the audience
            capabilities: List of capabilities to include in the token
            ttl: Time-to-live in seconds
            not_before: ISO timestamp before which the token is not valid
            proof: Proof of delegation (token ID of parent token)
            
        Returns:
            UCANToken: The created token
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
        Verify a UCAN token.
        
        Args:
            token_id: ID of the token to verify
            
        Returns:
            tuple: (is_valid, error_message)
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
        Revoke a UCAN token.
        
        Args:
            token_id: ID of the token to revoke
            revoker_did: DID of the revoker
            reason: Reason for revocation
            
        Returns:
            bool: Whether revocation was successful
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
        Get a token by ID.
        
        Args:
            token_id: ID of the token
            
        Returns:
            UCANToken: The token, or None if not found
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
        Check if a DID has a specific capability.
        
        Args:
            did: DID to check
            resource: Resource to check
            action: Action to check
            
        Returns:
            bool: Whether the DID has the capability
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
        Delegate a capability to another DID.
        
        Args:
            issuer_did: DID of the issuer
            audience_did: DID of the audience
            resource: Resource to delegate
            action: Action to delegate
            caveats: Caveats on the capability
            ttl: Time-to-live in seconds
            
        Returns:
            UCANToken: The created token, or None if delegation failed
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


if __name__ == "__main__":
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