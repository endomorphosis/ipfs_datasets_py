#!/usr/bin/env python3
"""
Demonstration of IPFS CID-based cache for TDFOL LLM converter.

This script demonstrates:
1. Cache key generation using IPFS CIDs
2. CID determinism and uniqueness
3. Cache operations with IPFS CIDs
4. CID validation and parsing
"""

from ipfs_datasets_py.logic.TDFOL.nl.cache_utils import (
    create_cache_cid,
    validate_cid,
    parse_cid
)
from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import LLMResponseCache


def demonstrate_cid_generation():
    """Demonstrate IPFS CID generation for cache keys."""
    print("=" * 70)
    print("1. IPFS CID Generation")
    print("=" * 70)
    
    # Example cache data
    data = {
        "text": "All contractors must pay taxes",
        "provider": "openai",
        "prompt_hash": "abc123"
    }
    
    # Generate CID
    cid = create_cache_cid(data)
    print(f"Input data: {data}")
    print(f"Generated CID: {cid}")
    print(f"CID prefix: {cid[:10]}... (starts with 'bafk' = CIDv1 base32)")
    print(f"CID length: {len(cid)} characters")
    print()


def demonstrate_cid_determinism():
    """Demonstrate that CIDs are deterministic."""
    print("=" * 70)
    print("2. CID Determinism")
    print("=" * 70)
    
    data = {"text": "test", "provider": "openai", "prompt_hash": "xyz"}
    
    # Generate same CID multiple times
    cid1 = create_cache_cid(data)
    cid2 = create_cache_cid(data)
    cid3 = create_cache_cid(data)
    
    print(f"Input data: {data}")
    print(f"CID #1: {cid1}")
    print(f"CID #2: {cid2}")
    print(f"CID #3: {cid3}")
    print(f"All identical: {cid1 == cid2 == cid3} ✓")
    print()


def demonstrate_cid_uniqueness():
    """Demonstrate that different inputs produce different CIDs."""
    print("=" * 70)
    print("3. CID Uniqueness")
    print("=" * 70)
    
    data1 = {"text": "text1", "provider": "openai", "prompt_hash": "a"}
    data2 = {"text": "text2", "provider": "openai", "prompt_hash": "a"}
    data3 = {"text": "text1", "provider": "anthropic", "prompt_hash": "a"}
    
    cid1 = create_cache_cid(data1)
    cid2 = create_cache_cid(data2)
    cid3 = create_cache_cid(data3)
    
    print(f"Data 1: {data1}")
    print(f"  CID: {cid1[:30]}...")
    print()
    print(f"Data 2: {data2}")
    print(f"  CID: {cid2[:30]}...")
    print()
    print(f"Data 3: {data3}")
    print(f"  CID: {cid3[:30]}...")
    print()
    print(f"All unique: {len({cid1, cid2, cid3}) == 3} ✓")
    print()


def demonstrate_cid_validation():
    """Demonstrate CID validation."""
    print("=" * 70)
    print("4. CID Validation")
    print("=" * 70)
    
    # Valid CID
    data = {"text": "hello", "provider": "openai", "prompt_hash": "xyz"}
    valid_cid = create_cache_cid(data)
    
    # Invalid CIDs
    invalid_cids = [
        "not_a_cid",
        "bafk_incomplete",
        "12345",
        ""
    ]
    
    print(f"Valid CID: {valid_cid}")
    print(f"  Validation: {validate_cid(valid_cid)} ✓")
    print()
    
    for invalid_cid in invalid_cids:
        print(f"Invalid CID: '{invalid_cid}'")
        print(f"  Validation: {validate_cid(invalid_cid)} ✓")
    print()


def demonstrate_cid_parsing():
    """Demonstrate CID parsing to extract metadata."""
    print("=" * 70)
    print("5. CID Parsing")
    print("=" * 70)
    
    data = {"text": "parse test", "provider": "openai", "prompt_hash": "abc"}
    cid = create_cache_cid(data)
    
    print(f"CID: {cid}")
    print()
    
    info = parse_cid(cid)
    print("Parsed CID metadata:")
    print(f"  Version: {info['version']} (CIDv1)")
    print(f"  Codec: {info['codec']} (raw binary)")
    print(f"  Hash function: {info['hashfun']['name']} (SHA2-256)")
    print(f"  Digest (first 32 chars): {info['hashfun']['digest'][:32]}...")
    print()


def demonstrate_cache_operations():
    """Demonstrate cache operations with IPFS CIDs."""
    print("=" * 70)
    print("6. Cache Operations")
    print("=" * 70)
    
    # Create cache
    cache = LLMResponseCache(max_size=10)
    
    # Store some responses
    print("Storing responses in cache:")
    cache.put("hello world", "openai", "hash1", "∀x.Hello(x)", 0.95)
    cache.put("contractors must pay", "openai", "hash2", "∀x.(Contractor(x) → O(Pay(x)))", 0.90)
    cache.put("eventually succeed", "anthropic", "hash3", "F(Succeed())", 0.88)
    
    print(f"  Stored 3 responses")
    print(f"  Cache size: {len(cache.cache)} entries")
    print()
    
    # Retrieve responses
    print("Retrieving responses from cache:")
    result1 = cache.get("hello world", "openai", "hash1")
    result2 = cache.get("contractors must pay", "openai", "hash2")
    result3 = cache.get("unknown text", "openai", "hash99")  # Cache miss
    
    if result1:
        formula, confidence = result1
        print(f"  Hit: 'hello world' → {formula} (confidence: {confidence})")
    
    if result2:
        formula, confidence = result2
        print(f"  Hit: 'contractors must pay' → {formula} (confidence: {confidence})")
    
    print(f"  Miss: 'unknown text' → None")
    print()
    
    # Cache statistics
    stats = cache.stats()
    print("Cache statistics:")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.2%}")
    print()


def main():
    """Run all demonstrations."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 10 + "IPFS CID-Based Cache Demonstration" + " " * 24 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    
    try:
        demonstrate_cid_generation()
        demonstrate_cid_determinism()
        demonstrate_cid_uniqueness()
        demonstrate_cid_validation()
        demonstrate_cid_parsing()
        demonstrate_cache_operations()
        
        print("=" * 70)
        print("✅ All demonstrations completed successfully!")
        print("=" * 70)
        print()
        print("Key Takeaways:")
        print("  • Cache keys are IPFS-native CIDs (content-addressed)")
        print("  • CIDs are deterministic (same input → same CID)")
        print("  • CIDs are unique (different input → different CID)")
        print("  • CIDs can be validated and parsed for metadata")
        print("  • Cache operations work seamlessly with CIDs")
        print("  • CIDs enable distributed caching with IPFS")
        print()
        
    except Exception as e:
        print(f"❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
