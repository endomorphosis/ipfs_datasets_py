"""
Example for the Security and Governance Module.

This example demonstrates how to:
- Configure and use the security system
- Create and manage users
- Encrypt and decrypt sensitive data
- Control access to resources
- Track data provenance
- Generate and review audit logs
"""

import os
import time
import json
import tempfile
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from ipfs_datasets_py.security import (
    initialize_security,
    get_security_manager,
    SecurityConfig,
    require_authentication,
    require_access,
    encrypted_context
)


def create_sensitive_dataset():
    """Create a sample sensitive dataset for demonstration."""
    # Create sample user data (this is just demonstration data)
    data = []
    for i in range(10):
        user = {
            "id": i,
            "name": f"User {i}",
            "email": f"user{i}@example.com",
            "ssn": f"123-45-{6789 - i}",  # Fake SSN
            "credit_card": f"4111-1111-1111-{1111 + i}",  # Fake credit card
            "address": f"123 Main St, Apt {i}, Anytown, CA 9{i}123"
        }
        data.append(user)
    
    return data


@require_authentication
def save_sensitive_data(data, output_file):
    """Save sensitive data to a file with encryption."""
    # Convert data to JSON string
    json_str = json.dumps(data, indent=2)
    
    # Get security manager
    manager = get_security_manager()
    
    # Generate encryption key
    key_id = manager.generate_encryption_key()
    print(f"Generated encryption key: {key_id}")
    
    # Encrypt data
    encrypted_data, metadata = manager.encrypt_data(json_str, key_id)
    
    # Save encrypted data
    with open(output_file, "wb") as f:
        f.write(encrypted_data)
    
    # Save metadata
    metadata_file = f"{output_file}.meta"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Saved encrypted data to {output_file}")
    print(f"Saved metadata to {metadata_file}")
    
    # Create resource policy
    manager.create_resource_policy(
        resource_id=output_file,
        resource_type="encrypted_file"
    )
    
    # Return key ID for later use
    return key_id


@require_authentication
@require_access(resource_id_param="input_file", access_type="read")
def load_sensitive_data(input_file, key_id):
    """Load and decrypt sensitive data from a file."""
    # Get security manager
    manager = get_security_manager()
    
    # Read encrypted data
    with open(input_file, "rb") as f:
        encrypted_data = f.read()
    
    # Decrypt data
    decrypted_data = manager.decrypt_data(encrypted_data, key_id)
    
    # Parse JSON
    data = json.loads(decrypted_data)
    
    print(f"Loaded and decrypted data from {input_file}")
    
    return data


def redact_sensitive_fields(data, fields_to_redact=None):
    """Redact sensitive fields in a dataset."""
    if fields_to_redact is None:
        fields_to_redact = ["ssn", "credit_card"]
    
    # Create a deep copy of the data
    redacted_data = []
    
    for item in data:
        redacted_item = item.copy()
        for field in fields_to_redact:
            if field in redacted_item:
                # Redact by replacing with asterisks
                value = redacted_item[field]
                if isinstance(value, str):
                    # Keep first and last character, redact the rest
                    if len(value) > 2:
                        redacted_item[field] = value[0] + "*" * (len(value) - 2) + value[-1]
                    else:
                        redacted_item[field] = "*" * len(value)
        
        redacted_data.append(redacted_item)
    
    return redacted_data


def record_dataset_provenance(output_file, source_dataset, process_description):
    """Record provenance information for a processed dataset."""
    # Get security manager
    manager = get_security_manager()
    
    # Calculate checksum
    with open(output_file, "rb") as f:
        file_data = f.read()
        checksum = hashlib.sha256(file_data).hexdigest()
    
    # Record provenance
    provenance = manager.record_provenance(
        data_id=output_file,
        source="security_example",
        process_steps=[
            {
                "name": "redaction",
                "description": process_description,
                "timestamp": datetime.now().isoformat()
            }
        ],
        parent_ids=[source_dataset],
        checksum=checksum,
        metadata={
            "output_type": "redacted_dataset",
            "created_at": datetime.now().isoformat()
        }
    )
    
    print(f"Recorded provenance for {output_file}")
    return provenance


def print_audit_logs():
    """Print recent audit logs."""
    # Get security manager
    manager = get_security_manager()
    
    # Get audit logs
    logs = manager.get_audit_logs(limit=20)
    
    if not logs:
        print("No audit logs found")
        return
    
    print(f"\nRECENT AUDIT LOGS ({len(logs)} entries):")
    print("-" * 80)
    
    for log in logs:
        # Format timestamp
        timestamp = datetime.fromisoformat(log.timestamp)
        formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        
        # Format log entry
        print(f"[{formatted_time}] {log.event_type} - User: {log.user}")
        print(f"  Action: {log.action} - Status: {log.status}")
        
        if log.resource_id:
            print(f"  Resource: {log.resource_type} - {log.resource_id}")
        
        # Print a few details if available
        if log.details:
            detail_str = ", ".join([f"{k}: {v}" for k, v in list(log.details.items())[:3]])
            print(f"  Details: {detail_str}")
        
        print("-" * 80)


def security_example():
    """
    Example demonstrating the security and governance features.
    
    This function:
    1. Configures the security system
    2. Creates users with different access levels
    3. Authenticates users
    4. Encrypts and decrypts sensitive data
    5. Manages access control to resources
    6. Tracks data provenance
    7. Reviews audit logs
    """
    # Create a temporary directory for the example
    temp_dir = tempfile.mkdtemp(prefix="ipfs_datasets_security_")
    print(f"Using temporary directory: {temp_dir}")
    
    try:
        # Step 1: Configure security
        print("\n=== Step 1: Configure Security System ===")
        
        security_dir = os.path.join(temp_dir, "security")
        os.makedirs(security_dir, exist_ok=True)
        
        config = SecurityConfig(
            enabled=True,
            security_dir=security_dir,
            encryption_algorithm="AES-256",
            log_all_access=True,
            track_provenance=True,
            audit_log_path=os.path.join(security_dir, "audit.log")
        )
        
        security = initialize_security(config)
        print("Security system initialized")
        
        # Step 2: Create users
        print("\n=== Step 2: Create Users ===")
        
        # Create admin user
        security.create_user("admin", "admin123", access_level="admin")
        print("Created admin user")
        
        # Create regular user
        security.create_user("user", "user123", access_level="read")
        print("Created regular user")
        
        # Step 3: Authenticate as admin
        print("\n=== Step 3: Authenticate as Admin ===")
        
        success = security.authenticate_user("admin", "admin123")
        if success:
            print("Authentication succeeded for admin user")
        else:
            print("Authentication failed for admin user")
            return
        
        # Step 4: Create and encrypt sensitive data
        print("\n=== Step 4: Create and Encrypt Sensitive Data ===")
        
        # Create sample data
        sensitive_data = create_sensitive_dataset()
        print(f"Created sample dataset with {len(sensitive_data)} records")
        
        # Save with encryption
        encrypted_file = os.path.join(temp_dir, "sensitive_data.enc")
        key_id = save_sensitive_data(sensitive_data, encrypted_file)
        
        # Step 5: Decrypt and verify data
        print("\n=== Step 5: Decrypt and Verify Data ===")
        
        # Load encrypted data
        decrypted_data = load_sensitive_data(encrypted_file, key_id)
        
        # Verify
        if decrypted_data == sensitive_data:
            print("Decryption successful - data matches original")
        else:
            print("Decryption error - data does not match original")
        
        # Step 6: Process data with redaction
        print("\n=== Step 6: Process Data with Redaction ===")
        
        # Redact sensitive fields
        redacted_data = redact_sensitive_fields(sensitive_data)
        
        # Write redacted data
        redacted_file = os.path.join(temp_dir, "redacted_data.json")
        with open(redacted_file, "w") as f:
            json.dump(redacted_data, f, indent=2)
        
        print(f"Created redacted dataset with {len(redacted_data)} records")
        
        # Sample of original and redacted
        print("\nSample record (original):")
        print(json.dumps(sensitive_data[0], indent=2))
        
        print("\nSample record (redacted):")
        print(json.dumps(redacted_data[0], indent=2))
        
        # Step 7: Record provenance
        print("\n=== Step 7: Record Data Provenance ===")
        
        provenance = record_dataset_provenance(
            redacted_file, 
            encrypted_file,
            "Redacted sensitive fields: ssn, credit_card"
        )
        
        # Step 8: Switch user and test access
        print("\n=== Step 8: Switch User and Test Access ===")
        
        # Authenticate as regular user
        security.authenticate_user("user", "user123")
        print("Authenticated as regular user")
        
        # Try to access the encrypted file (should fail)
        try:
            decrypted_data = load_sensitive_data(encrypted_file, key_id)
            print("Access granted to encrypted file (unexpected)")
        except PermissionError as e:
            print(f"Access denied to encrypted file as expected: {str(e)}")
        
        # Step 9: Update access policy
        print("\n=== Step 9: Update Access Policy ===")
        
        # Switch back to admin
        security.authenticate_user("admin", "admin123")
        print("Authenticated as admin")
        
        # Update policy to give read access to regular user
        security.update_resource_policy(
            resource_id=encrypted_file,
            updates={
                "read_access": ["admin", "user"],
                "write_access": ["admin"]
            }
        )
        print(f"Updated access policy for {encrypted_file}")
        
        # Step 10: Verify updated access
        print("\n=== Step 10: Verify Updated Access ===")
        
        # Authenticate as regular user again
        security.authenticate_user("user", "user123")
        print("Authenticated as regular user")
        
        # Try to access the encrypted file (should succeed now)
        try:
            decrypted_data = load_sensitive_data(encrypted_file, key_id)
            print("Access granted to encrypted file (expected)")
        except PermissionError as e:
            print(f"Access denied to encrypted file (unexpected): {str(e)}")
        
        # Step 11: Use encrypted context manager
        print("\n=== Step 11: Use Encrypted Context Manager ===")
        
        # Create some new data
        report_data = {
            "title": "Monthly Report",
            "date": datetime.now().isoformat(),
            "departments": [
                {"name": "Engineering", "headcount": 45, "budget": 500000},
                {"name": "Marketing", "headcount": 15, "budget": 300000},
                {"name": "Sales", "headcount": 30, "budget": 400000}
            ]
        }
        
        # Convert to string
        report_json = json.dumps(report_data, indent=2)
        
        # Save using context manager
        report_file = os.path.join(temp_dir, "report.enc")
        
        with encrypted_context(report_json) as (data, key_id):
            # Context provides decrypted data and key ID
            # For new data, it just passes through the data and creates a new key
            
            # Encrypt and save
            encrypted_data, metadata = security.encrypt_data(data, key_id)
            
            with open(report_file, "wb") as f:
                f.write(encrypted_data)
            
            # Save metadata
            metadata_file = f"{report_file}.meta"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
            
            print(f"Saved encrypted report to {report_file}")
            print(f"Using key: {key_id}")
        
        # Step 12: Check audit logs
        print("\n=== Step 12: Check Audit Logs ===")
        
        # Switch back to admin for viewing logs
        security.authenticate_user("admin", "admin123")
        
        # Print audit logs
        print_audit_logs()
        
        print("\nSecurity example completed successfully!")
        print(f"Example files in: {temp_dir}")
        
        return {
            "temp_dir": temp_dir,
            "sensitive_file": encrypted_file,
            "redacted_file": redacted_file,
            "key_id": key_id
        }
        
    except Exception as e:
        print(f"\nError in security example: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Check for cryptography module
    try:
        import cryptography
        has_crypto = True
    except ImportError:
        has_crypto = False
        print("Warning: cryptography module not available. Install with: pip install cryptography")
    
    if has_crypto:
        # Run the example
        security_example()