from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class BloomFilter:
    """Small Bloom filter implementation (no external deps).

    Not optimized; intended for shard routing metadata, not heavy-duty set ops.
    """

    num_bits: int
    num_hashes: int
    bits: bytearray

    @classmethod
    def create(cls, *, num_bits: int, num_hashes: int) -> "BloomFilter":
        if num_bits <= 0:
            raise ValueError("num_bits must be > 0")
        if num_hashes <= 0:
            raise ValueError("num_hashes must be > 0")
        num_bytes = (num_bits + 7) // 8
        return cls(num_bits=num_bits, num_hashes=num_hashes, bits=bytearray(num_bytes))

    def _positions(self, data: bytes) -> list[int]:
        # Derive multiple hashes using BLAKE2b keyed by i.
        pos: list[int] = []
        for i in range(self.num_hashes):
            h = hashlib.blake2b(data, digest_size=8, person=i.to_bytes(4, "big")).digest()
            value = int.from_bytes(h, "big")
            pos.append(value % self.num_bits)
        return pos

    def add(self, item: str) -> None:
        data = item.encode("utf-8", errors="strict")
        for p in self._positions(data):
            self.bits[p // 8] |= 1 << (p % 8)

    def might_contain(self, item: str) -> bool:
        data = item.encode("utf-8", errors="strict")
        for p in self._positions(data):
            if not (self.bits[p // 8] & (1 << (p % 8))):
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "num_bits": self.num_bits,
            "num_hashes": self.num_hashes,
            "bits_hex": self.bits.hex(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BloomFilter":
        bits = bytearray(bytes.fromhex(d["bits_hex"]))
        return cls(num_bits=int(d["num_bits"]), num_hashes=int(d["num_hashes"]), bits=bits)
