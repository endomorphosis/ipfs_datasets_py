# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/audit/security_provenance_integration.py'

## SecurityProvenanceIntegrator

```python
class SecurityProvenanceIntegrator:
    """
    Integrates the enhanced security system with data provenance tracking.

This class provides bidirectional integration between the enhanced security
system and data provenance tracking, enabling:

1. Security-aware provenance tracking:
   - Add security classifications to provenance records
   - Protect provenance records based on data sensitivity
   - Sign provenance records for integrity verification

2. Provenance-aware security enforcement:
   - Use lineage information for access control decisions
   - Create security policies based on data provenance
   - Verify data transformation chains for sensitive operations
    """
```
## __init__

```python
def __init__(self, security_manager = None, provenance_manager = None, audit_integrator = None):
    """
    Initialize the security-provenance integrator.

Args:
    security_manager: EnhancedSecurityManager instance (optional)
    provenance_manager: EnhancedProvenanceManager instance (optional)
    audit_integrator: AuditProvenanceIntegrator instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _ace_to_dict

```python
def _ace_to_dict(self, ace: AccessControlEntry) -> Dict[str, Any]:
    """
    Convert an AccessControlEntry to a simplified dictionary.

Args:
    ace: The AccessControlEntry to convert

Returns:
    Dict[str, Any]: Dictionary representation of the ACE
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _get_document_classification

```python
def _get_document_classification(self, document_id: str) -> Optional[DataClassification]:
    """
    Get the highest classification level in a document.

Args:
    document_id: The document ID

Returns:
    Optional[DataClassification]: The highest classification level
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _record_to_dict

```python
def _record_to_dict(self, record: Any) -> Dict[str, Any]:
    """
    Convert a provenance record to a dictionary.

Args:
    record: The provenance record

Returns:
    Dict[str, Any]: Dictionary representation of the record
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _verify_boundary_access_controls

```python
def _verify_boundary_access_controls(self, from_doc: str, to_doc: str) -> bool:
    """
    Verify that appropriate access controls exist at a document boundary.

Args:
    from_doc: The source document ID
    to_doc: The target document ID

Returns:
    bool: Whether appropriate access controls exist
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _verify_boundary_integrity

```python
def _verify_boundary_integrity(self, from_doc: str, to_doc: str) -> bool:
    """
    Verify integrity preservation across a document boundary.

Args:
    from_doc: The source document ID
    to_doc: The target document ID

Returns:
    bool: Whether integrity is preserved across the boundary
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## _verify_lineage_chain

```python
def _verify_lineage_chain(self, lineage_records: List[Any]) -> bool:
    """
    Verify the integrity of a lineage chain.

Args:
    lineage_records: The lineage records to verify

Returns:
    bool: Whether the lineage chain is valid
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## add_security_metadata_to_record

```python
def add_security_metadata_to_record(self, record_id: str, user_id: Optional[str] = None) -> bool:
    """
    Add security-related metadata to a provenance record.

This method enhances provenance records with security classifications,
access control information, and cryptographic verification.

Args:
    record_id: The ID of the provenance record to enhance
    user_id: The user performing the operation (optional)

Returns:
    bool: Whether the operation was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## check_access_with_lineage

```python
def check_access_with_lineage(self, user_id: str, resource_id: str, operation: str, max_depth: int = 2) -> Tuple[AccessDecision, Dict[str, Any]]:
    """
    Check access using both direct permissions and data lineage information.

This method enhances access control by considering data lineage when making
access decisions. It can enforce security policies like:
- Deny access if upstream data sources have higher classification
- Require additional authorization for data derived from sensitive sources
- Verify transformation chain integrity for sensitive operations

Args:
    user_id: The user requesting access
    resource_id: The resource being accessed
    operation: The operation being performed
    max_depth: Maximum lineage traversal depth

Returns:
    Tuple[AccessDecision, Dict[str, Any]]: Access decision and context
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## create_provenance_based_security_policy

```python
def create_provenance_based_security_policy(self, policy_id: str, name: str, resource_pattern: str, lineage_rules: List[Dict[str, Any]], user_id: Optional[str] = None) -> bool:
    """
    Create a security policy based on data provenance requirements.

This method creates a security policy that enforces rules based on data
lineage and provenance information.

Args:
    policy_id: Unique ID for the policy
    name: Human-readable name for the policy
    resource_pattern: Pattern for resources this policy applies to
    lineage_rules: Rules for lineage verification
    user_id: User creating the policy (optional)

Returns:
    bool: Whether the policy was successfully created
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_security_provenance_integrator

```python
def get_security_provenance_integrator(security_manager = None, provenance_manager = None) -> SecurityProvenanceIntegrator:
    """
    Get a security-provenance integrator instance.

Args:
    security_manager: EnhancedSecurityManager instance (optional)
    provenance_manager: EnhancedProvenanceManager instance (optional)

Returns:
    SecurityProvenanceIntegrator: The integrator instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## record_secure_transformation

```python
def record_secure_transformation(self, input_ids: List[str], output_id: str, transformation_type: str, parameters: Dict[str, Any], user_id: str, verify_lineage: bool = True, classification: Optional[DataClassification] = None) -> Optional[str]:
    """
    Record a secure data transformation with full security context.

This method records a transformation operation with:
- Security classifications for both inputs and outputs
- Access control enforcement before recording
- Cryptographic verification for integrity
- Optional lineage verification

Args:
    input_ids: IDs of the input data
    output_id: ID of the output data
    transformation_type: Type of transformation
    parameters: Transformation parameters
    user_id: User performing the transformation
    verify_lineage: Whether to verify upstream lineage for sensitive inputs
    classification: Optional classification for the output data

Returns:
    Optional[str]: The record ID if successful, None otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## secure_provenance_operation

```python
def secure_provenance_operation(user_id_arg: str, data_id_arg: str, action: str = "provenance_operation"):
    """
    Decorator for securing provenance operations with access control and auditing.

Args:
    user_id_arg: Name of the argument containing the user ID
    data_id_arg: Name of the argument containing the data ID
    action: The action being performed

Returns:
    Callable: Decorated function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## secure_provenance_query

```python
def secure_provenance_query(self, query_params: Dict[str, Any], user_id: str, include_cross_document: bool = False) -> Dict[str, Any]:
    """
    Perform a security-aware provenance query.

This method performs a provenance query with security checks, filtering
results based on user permissions and data classifications.

Args:
    query_params: Query parameters
    user_id: User performing the query
    include_cross_document: Whether to include cross-document analysis

Returns:
    Dict[str, Any]: Query results with security information
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## verify_cross_document_security

```python
def verify_cross_document_security(self, document_ids: List[str], user_id: str) -> Dict[str, Any]:
    """
    Verify security across document boundaries.

This method analyzes cross-document data flows to identify security
issues like unauthorized data transfers, classification violations,
or integrity issues.

Args:
    document_ids: List of document IDs to analyze
    user_id: User requesting the verification

Returns:
    Dict[str, Any]: Verification results
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## verify_provenance_integrity

```python
def verify_provenance_integrity(self, record_id: str) -> Dict[str, Any]:
    """
    Verify the integrity of a provenance record.

Args:
    record_id: The ID of the provenance record to verify

Returns:
    Dict[str, Any]: Verification results
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityProvenanceIntegrator

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
