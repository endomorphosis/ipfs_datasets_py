# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ucan.py'

Files last updated: 1751411025.1031897

Stub file last updated: 2025-07-07 02:11:02

## UCANCapability

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UCANKeyPair

```python
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
    ...     public_key_pem="-----BEGIN PUBLIC KEY-----\n...",
    ...     private_key_pem="-----BEGIN PRIVATE KEY-----\n..."
    ... )

Note:
    Private keys should be handled with extreme care and stored securely.
    Consider using environment variables or secure key management systems
    for production deployments.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UCANManager

```python
class UCANManager:
    """
    Manager for UCAN operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UCANRevocation

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UCANToken

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the UCAN (User Controlled Authorization Networks) manager.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _load_keypairs

```python
def _load_keypairs(self) -> None:
    """
    Load cryptographic keypairs from persistent storage.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _load_revocations

```python
def _load_revocations(self) -> None:
    """
    Load revocations from persistent storage.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _load_tokens

```python
def _load_tokens(self) -> None:
    """
    Load UCAN tokens from persistent storage.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _save_keypairs

```python
def _save_keypairs(self) -> None:
    """
    Save all keypairs to persistent storage as JSON.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _save_revocations

```python
def _save_revocations(self) -> None:
    """
    Save UCAN token revocations to persistent storage.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## _save_tokens

```python
def _save_tokens(self) -> None:
    """
    Save UCAN tokens to persistent JSON storage.

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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## create_token

```python
def create_token(self, issuer_did: str, audience_did: str, capabilities: List[UCANCapability], ttl: int = DEFAULT_TTL, not_before: Optional[str] = None, proof: Optional[str] = None) -> UCANToken:
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## delegate_capability

```python
def delegate_capability(self, issuer_did: str, audience_did: str, resource: str, action: str, caveats: Optional[Dict[str, Any]] = None, ttl: int = DEFAULT_TTL) -> Optional[UCANToken]:
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## generate_keypair

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## get_capabilities

```python
def get_capabilities(self, did: str) -> List[UCANCapability]:
    """
    Get all capabilities granted to a DID.

Args:
    did: DID to get capabilities for

Returns:
    list: List of capabilities
    """
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## get_instance

```python
@classmethod
def get_instance(cls) -> "UCANManager":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## get_keypair

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## get_token

```python
def get_token(self, token_id: str) -> Optional[UCANToken]:
    """
    Get a token by ID.

Args:
    token_id: ID of the token

Returns:
    UCANToken: The token, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## get_ucan_manager

```python
def get_ucan_manager() -> UCANManager:
    """
    Get the UCAN manager instance.

Returns:
    UCANManager: The UCAN manager
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## has_capability

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## import_keypair

```python
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
            >>> public_pem = "-----BEGIN PUBLIC KEY-----
..."
            >>> private_pem = "-----BEGIN PRIVATE KEY-----
..."
            >>> keypair = ucan_manager.import_keypair(public_pem, private_pem)
            >>> print(keypair.did)
            did:key:abc123...
        
        Note:
            The DID is generated by hashing the public key PEM content with SHA-256.
            The keypair is automatically saved to persistent storage.
        
    """
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## initialize

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## initialize_ucan

```python
def initialize_ucan() -> UCANManager:
    """
    Initialize the UCAN manager.

Returns:
    UCANManager: The initialized UCAN manager
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## revoke_token

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager

## ucan_demonstration

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## verify_token

```python
def verify_token(self, token_id: str) -> Tuple[bool, Optional[str]]:
    """
    Verify a UCAN token.

Args:
    token_id: ID of the token to verify

Returns:
    tuple: (is_valid, error_message)
    """
```
* **Async:** False
* **Method:** True
* **Class:** UCANManager
