# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/security.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 02:11:02

## AuditLogEntry

```python
@dataclass
class AuditLogEntry:
    """
    Audit log entry for security-related events.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DataLineage

```python
@dataclass
class DataLineage:
    """
    Detailed lineage information tracking data through its lifecycle.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DataProvenance

```python
@dataclass
class DataProvenance:
    """
    Comprehensive provenance information for a piece of data.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EncryptionKey

```python
@dataclass
class EncryptionKey:
    """
    Encryption key with metadata.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessStep

```python
@dataclass
class ProcessStep:
    """
    A single processing step in a data transformation pipeline.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResourcePolicy

```python
@dataclass
class ResourcePolicy:
    """
    Access policy for a resource.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityConfig

```python
@dataclass
class SecurityConfig:
    """
    Configuration for security features.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SecurityManager

```python
class SecurityManager:
    """
    Main class for security and governance features.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UserCredentials

```python
@dataclass
class UserCredentials:
    """
    User credentials and permissions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the security manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _check_key_capability

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _create_key_capabilities

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_lineage_as_d3

```python
def _format_lineage_as_d3(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format lineage visualization for D3.js force-directed graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_lineage_as_dot

```python
def _format_lineage_as_dot(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format lineage visualization as DOT format for GraphViz.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_lineage_as_mermaid

```python
def _format_lineage_as_mermaid(self, visualization: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format lineage visualization as Mermaid flowchart.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_report_as_html

```python
def _format_report_as_html(self, report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format the provenance report as HTML.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_report_as_markdown

```python
def _format_report_as_markdown(self, report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format the provenance report as Markdown.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _format_report_as_text

```python
def _format_report_as_text(self, report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format the provenance report as human-readable text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_derived_data_ids

```python
def _get_derived_data_ids(self, data_id: str) -> List[str]:
    """
    Helper to find all data items derived from the given data ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_last_verification_time

```python
def _get_last_verification_time(self, provenance: DataProvenance) -> Optional[str]:
    """
    Helper to get the last verification time from a provenance record.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_mermaid_node_style

```python
def _get_mermaid_node_style(self, node_type: str) -> str:
    """
    Helper to determine node style based on type for Mermaid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_node_color

```python
def _get_node_color(self, node_type: str) -> str:
    """
    Helper to determine node color based on type for GraphViz.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_node_group

```python
def _get_node_group(self, node_type: str) -> int:
    """
    Helper to determine node group (for coloring) based on type for D3.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _get_node_label

```python
def _get_node_label(self, provenance: DataProvenance) -> str:
    """
    Helper to generate a readable label for a node in the lineage graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _hash_password

```python
def _hash_password(self, password: str, salt: bytes) -> str:
    """
    Hash a password using PBKDF2.

Args:
    password: Password to hash
    salt: Salt for the hash

Returns:
    str: Base64-encoded password hash
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _load_encryption_keys

```python
def _load_encryption_keys(self) -> None:
    """
    Load encryption keys from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _load_policies

```python
def _load_policies(self) -> None:
    """
    Load resource policies from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _load_users

```python
def _load_users(self) -> None:
    """
    Load users from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _log_audit_event

```python
def _log_audit_event(self, event_type: str, user: str, action: str, resource_id: Optional[str] = None, resource_type: Optional[str] = None, details: Optional[Dict[str, Any]] = None, source_ip: Optional[str] = None, success: bool = True) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _read_provenance_log

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _save_encryption_keys

```python
def _save_encryption_keys(self) -> None:
    """
    Save encryption keys to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _save_policies

```python
def _save_policies(self) -> None:
    """
    Save resource policies to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _save_users

```python
def _save_users(self) -> None:
    """
    Save users to storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _write_audit_log

```python
def _write_audit_log(self, event: AuditLogEntry) -> bool:
    """
    Write an audit event to the audit log.

Args:
    event: Audit event to write

Returns:
    bool: Whether the write was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## _write_provenance_log

```python
def _write_provenance_log(self, provenance: DataProvenance) -> bool:
    """
    Write provenance information to the provenance log.

Args:
    provenance: Provenance information to write

Returns:
    bool: Whether the write was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## authenticate_user

```python
def authenticate_user(self, username: str, password: str) -> bool:
    """
    Authenticate a user.

Args:
    username: Username to authenticate
    password: Password to authenticate

Returns:
    bool: Whether authentication was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## check_access

```python
def check_access(self, resource_id: str, access_type: str) -> bool:
    """
    Check if the current user has access to a resource.

Args:
    resource_id: ID of the resource
    access_type: Type of access (read, write, admin)

Returns:
    bool: Whether the user has access
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## complete_transformation_step

```python
def complete_transformation_step(self, data_id: str, step_id: str, status: str = "completed", error: Optional[str] = None, outputs: Optional[List[str]] = None, metrics: Optional[Dict[str, Any]] = None) -> bool:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## configure

```python
def configure(self, config: SecurityConfig) -> None:
    """
    Configure the security manager.

Args:
    config: Configuration for security features
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## create_resource_policy

```python
def create_resource_policy(self, resource_id: str, resource_type: str, owner: Optional[str] = None) -> ResourcePolicy:
    """
    Create a new resource access policy.

Args:
    resource_id: ID of the resource
    resource_type: Type of the resource
    owner: Owner of the resource (defaults to current user)

Returns:
    ResourcePolicy: The created policy
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## create_user

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decrypt_data

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## decrypt_file

```python
def decrypt_file(self, input_file: Union[str, BinaryIO], output_file: Union[str, BinaryIO], key_id: str, requestor_did: Optional[str] = None) -> bool:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## delegate_encryption_capability

```python
def delegate_encryption_capability(self, key_id: str, delegator_did: str, delegatee_did: str, action: str, caveats: Optional[Dict[str, Any]] = None, ttl: Optional[int] = None) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## encrypt_data

```python
def encrypt_data(self, data: Union[bytes, str], key_id: Optional[str] = None, requestor_did: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## encrypt_file

```python
def encrypt_file(self, input_file: Union[str, BinaryIO], output_file: Union[str, BinaryIO], key_id: Optional[str] = None, requestor_did: Optional[str] = None) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## encrypted_context

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_encryption_key

```python
def generate_encryption_key(self, algorithm: Optional[str] = None, context: Optional[Dict[str, Any]] = None, with_ucan: bool = True) -> str:
    """
    Generate a new encryption key.

Args:
    algorithm: Encryption algorithm to use
    context: Context for the key
    with_ucan: Whether to create UCAN capabilities for this key

Returns:
    str: Key ID for the generated key
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## generate_lineage_visualization

```python
def generate_lineage_visualization(self, data_id: str, format: str = "dot", max_depth: int = 3, direction: str = "both", include_attributes: bool = False) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## generate_provenance_report

```python
def generate_provenance_report(self, data_id: str, report_type: str = "detailed", format: str = "json", include_lineage: bool = True, include_access_history: bool = True) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## get_audit_logs

```python
def get_audit_logs(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100, offset: int = 0) -> List[AuditLogEntry]:
    """
    Get audit logs, optionally filtered.

Args:
    filters: Filters to apply
    limit: Maximum number of logs to return
    offset: Offset for pagination

Returns:
    list: List of audit log entries
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## get_data_lineage_graph

```python
def get_data_lineage_graph(self, data_id: str, max_depth: int = 3, direction: str = "both") -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## get_instance

```python
@classmethod
def get_instance(cls) -> "SecurityManager":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## get_provenance

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## get_security_manager

```python
def get_security_manager() -> SecurityManager:
    """
    Get the security manager instance.

Returns:
    SecurityManager: The security manager
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## initialize

```python
@classmethod
def initialize(cls, config: Optional[SecurityConfig] = None) -> "SecurityManager":
    """
    Initialize the security manager.

Args:
    config: Configuration for security features

Returns:
    SecurityManager: The initialized security manager
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## initialize_security

```python
def initialize_security(config: Optional[SecurityConfig] = None) -> SecurityManager:
    """
    Initialize the security manager.

Args:
    config: Configuration for security features

Returns:
    SecurityManager: The initialized security manager
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## process_node

```python
def process_node(node_id, current_depth = 0, node_type = "target"):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## record_data_access

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## record_provenance

```python
def record_provenance(self, data_id: str, source: str, process_steps: List[Dict[str, Any]], parent_ids: List[str], checksum: str, metadata: Optional[Dict[str, Any]] = None, data_type: str = "unknown", schema: Optional[Dict[str, Any]] = None, size_bytes: Optional[int] = None, record_count: Optional[int] = None, content_type: Optional[str] = None, lineage_info: Optional[Dict[str, Any]] = None, transformation_history: Optional[List[Dict[str, Any]]] = None, tags: Optional[List[str]] = None) -> DataProvenance:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## record_transformation_step

```python
def record_transformation_step(self, data_id: str, operation: str, description: str, tool: str, parameters: Dict[str, Any], inputs: List[str], outputs: Optional[List[str]] = None, metrics: Optional[Dict[str, Any]] = None, environment: Optional[Dict[str, Any]] = None) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## require_access

```python
def require_access(resource_id_param: str, access_type: str):
    """
    Decorator to require access to a resource for a function.

Args:
    resource_id_param: Name of the parameter containing the resource ID
    access_type: Type of access required (read, write, admin)

Returns:
    Callable: Decorator function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## require_authentication

```python
def require_authentication(func):
    """
    Decorator to require authentication for a function.

Args:
    func: Function to decorate

Returns:
    Callable: Decorated function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## revoke_encryption_capability

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## search_provenance

```python
def search_provenance(self, criteria: Dict[str, Any], limit: int = 100) -> List[DataProvenance]:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## update_resource_policy

```python
def update_resource_policy(self, resource_id: str, updates: Dict[str, Any]) -> bool:
    """
    Update a resource access policy.

Args:
    resource_id: ID of the resource
    updates: Dictionary of updates to apply

Returns:
    bool: Whether the update was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## verify_data_provenance

```python
def verify_data_provenance(self, data_id: str, verification_method: str = "checksum", verification_details: Optional[Dict[str, Any]] = None) -> bool:
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
```
* **Async:** False
* **Method:** True
* **Class:** SecurityManager

## wrapper

```python
@wraps(func)
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## wrapper

```python
@wraps(func)
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
