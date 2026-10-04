# UCAN Callables Gherkin Test Specifications

This directory contains Gherkin feature files for each callable method in the `UCANManager` class from `ipfs_datasets_py/ucan.py`.

## Purpose

These Gherkin files provide behavioral specifications for UCAN (User Controlled Authorization Networks) functionality. Each file explicitly tests a single callable method and uses concrete scenarios with minimal adverbs and adjectives.

## Files

| File | Callable | Description |
|------|----------|-------------|
| `get_instance.feature` | `UCANManager.get_instance()` | Get singleton instance of UCANManager |
| `initialize.feature` | `UCANManager.initialize()` | Initialize manager and load storage |
| `generate_keypair.feature` | `UCANManager.generate_keypair()` | Generate new RSA keypair with DID |
| `import_keypair.feature` | `UCANManager.import_keypair()` | Import existing keypair |
| `get_keypair.feature` | `UCANManager.get_keypair()` | Retrieve keypair by DID |
| `create_token.feature` | `UCANManager.create_token()` | Create UCAN authorization token |
| `verify_token.feature` | `UCANManager.verify_token()` | Verify token validity and signature |
| `revoke_token.feature` | `UCANManager.revoke_token()` | Revoke a token |
| `get_token.feature` | `UCANManager.get_token()` | Retrieve token by ID |
| `get_capabilities.feature` | `UCANManager.get_capabilities()` | Get all capabilities for a DID |
| `has_capability.feature` | `UCANManager.has_capability()` | Check if DID has specific capability |
| `delegate_capability.feature` | `UCANManager.delegate_capability()` | Delegate capability to another DID |

## UCAN Overview

UCAN (User Controlled Authorization Networks) is a capability-based authorization system that uses:

- **DIDs**: Decentralized Identifiers for entities
- **Keypairs**: RSA keypairs for cryptographic signing
- **Tokens**: JWT-based authorization tokens with capabilities
- **Capabilities**: Resource + Action + Caveats permissions
- **Delegation**: Ability to delegate capabilities to others
- **Revocation**: Ability to invalidate tokens

## Supported Capabilities

The following capability actions are supported:
- `encrypt` - Can encrypt data
- `decrypt` - Can decrypt data
- `delegate` - Can delegate capabilities to others
- `revoke` - Can revoke capabilities
- `manage` - Can manage keys

## Test Coverage

Total scenarios across all files: **100+**
Total lines of Gherkin: **647**

Each callable has multiple scenarios covering:
- Happy path (successful operations)
- Edge cases (empty inputs, missing data)
- Error conditions (not initialized, missing dependencies)
- Authorization checks (permissions, delegation chains)
- State validation (expiration, revocation)

## Usage

These Gherkin files serve as:
1. **Specification**: Precise behavioral requirements for each callable
2. **Test templates**: Basis for implementing actual test code
3. **Documentation**: Human-readable descriptions of functionality

To implement tests from these specifications:
1. Use a Gherkin test framework (e.g., pytest-bdd, behave)
2. Create step definitions matching the Given/When/Then steps
3. Implement fixtures for Background setup
4. Run tests to verify UCAN implementation

## Notes

- Each feature file explicitly mentions the callable it tests in the title
- Scenarios use concrete values (e.g., "did:key:alice") rather than abstract descriptions
- Steps avoid unnecessary adverbs and adjectives
- Error scenarios test RuntimeError and ValueError conditions
- Delegation chain verification is covered in verify_token scenarios
