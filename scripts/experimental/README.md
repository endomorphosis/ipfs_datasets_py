# Experimental Scripts

This directory contains **experimental and prototype** code that is not ready for production use. These scripts demonstrate concepts, test ideas, or serve as design documents for future features.

---

## ⚠️ Status: EXPERIMENTAL

**Do not use these scripts in production environments.**

These scripts may:
- Reference non-existent libraries or modules
- Contain incomplete implementations
- Have unresolved TODOs and design issues
- Change significantly or be removed without notice

---

## Current Experimental Scripts

### federated_search.py

**Status:** Prototype/Design Document  
**Purpose:** Demonstrates federated search architecture for distributed IPFS datasets

**Known Issues:**
- Requires `py_libp2p` which is not yet integrated into the project
- References non-existent modules:
  - `NetworkProtocol` (from libp2p_kit)
  - `ShardMetadata` (from libp2p_kit)
  - `INetStream` (from py_libp2p)
- Not production-ready

**Future Work:**
- Integrate py_libp2p when available
- Implement missing NetworkProtocol and ShardMetadata classes
- Add comprehensive tests
- Target version: v3.0+ (2027+)

**What It Demonstrates:**
- Federated search architecture concepts
- Vector similarity search across distributed nodes
- Hybrid search combining multiple search types
- Result aggregation strategies
- Privacy-preserving search patterns

---

## Guidelines for Experimental Code

### When to Add Code Here

Add code to this directory when:
1. Exploring new concepts or architectures
2. Creating design documents through code
3. Prototyping features for future releases
4. Dependencies are not yet available
5. Implementation is incomplete but demonstrates ideas

### When to Promote Code

Move code out of experimental when:
1. All dependencies are available and integrated
2. Implementation is complete and tested
3. Code is production-ready
4. Documentation is comprehensive
5. Approved for inclusion in stable release

### Documentation Requirements

Each experimental script should have:
- Clear **Status** section explaining experimental nature
- **Known Issues** documenting limitations
- **Future Work** outlining path to production
- **What It Demonstrates** explaining the concepts

---

## Related Documentation

- [ROADMAP.md](../../ipfs_datasets_py/knowledge_graphs/ROADMAP.md) - Future feature plans
- [IMPLEMENTATION_STATUS.md](../../ipfs_datasets_py/knowledge_graphs/IMPLEMENTATION_STATUS.md) - Current module status

---

**Last Updated:** 2026-02-18  
**Maintained By:** IPFS Datasets Team
