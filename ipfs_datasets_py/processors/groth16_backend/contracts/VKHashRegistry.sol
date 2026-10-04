// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/// @title VKHashRegistry
/// @notice Minimal on-chain registry mapping (circuitId, version) -> verifying key hash.
/// @dev This is intentionally small and policy-focused:
///      - circuitId is a bytes32 identifier (e.g., keccak256("mvp_knowledge_of_axioms"))
///      - version is a uint64
///      - vkHash is a bytes32 (e.g., SHA-256 digest interpreted as bytes32)
contract VKHashRegistry {
    address public owner;

    struct Entry {
        bytes32 vkHash;
        bool deprecated;
        uint64 registeredAt;
    }

    mapping(bytes32 => mapping(uint64 => Entry)) private _entries;

    event OwnerChanged(address indexed previousOwner, address indexed newOwner);
    event VKRegistered(bytes32 indexed circuitId, uint64 indexed version, bytes32 vkHash);
    event VKDeprecated(bytes32 indexed circuitId, uint64 indexed version, bool deprecated);

    modifier onlyOwner() {
        require(msg.sender == owner, "only owner");
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnerChanged(address(0), msg.sender);
    }

    function setOwner(address newOwner) external onlyOwner {
        require(newOwner != address(0), "newOwner=0");
        emit OwnerChanged(owner, newOwner);
        owner = newOwner;
    }

    /// @notice Register a verifying key hash for a circuit version.
    /// @param circuitId Circuit identifier (bytes32)
    /// @param version Circuit version (uint64)
    /// @param vkHash Verifying key hash (bytes32)
    /// @param overwrite Allow overwriting an existing entry
    function registerVK(bytes32 circuitId, uint64 version, bytes32 vkHash, bool overwrite) external onlyOwner {
        require(circuitId != bytes32(0), "circuitId=0");
        require(vkHash != bytes32(0), "vkHash=0");

        Entry storage e = _entries[circuitId][version];
        if (!overwrite) {
            require(e.vkHash == bytes32(0), "already registered");
        }

        e.vkHash = vkHash;
        e.deprecated = false;
        e.registeredAt = uint64(block.timestamp);

        emit VKRegistered(circuitId, version, vkHash);
    }

    /// @notice Deprecate or un-deprecate an existing VK entry.
    function setDeprecated(bytes32 circuitId, uint64 version, bool deprecated) external onlyOwner {
        Entry storage e = _entries[circuitId][version];
        require(e.vkHash != bytes32(0), "not registered");
        e.deprecated = deprecated;
        emit VKDeprecated(circuitId, version, deprecated);
    }

    /// @notice Fetch the VK entry for (circuitId, version).
    /// @return vkHash The VK hash
    /// @return deprecated Whether this version is deprecated
    /// @return registeredAt Block timestamp when registered
    function getVK(bytes32 circuitId, uint64 version) external view returns (bytes32 vkHash, bool deprecated, uint64 registeredAt) {
        Entry storage e = _entries[circuitId][version];
        return (e.vkHash, e.deprecated, e.registeredAt);
    }

    function isRegistered(bytes32 circuitId, uint64 version) external view returns (bool) {
        return _entries[circuitId][version].vkHash != bytes32(0);
    }
}
